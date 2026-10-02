import logging
from typing import Any
from urllib.parse import quote

import httpx
from pydantic import SecretStr

from backend.app.ingestion.http import HttpSource, MalformedSourceResponse
from backend.app.ingestion.models import RawMention


logger = logging.getLogger(__name__)


class YouTubeAPIError(RuntimeError):
    def __init__(self, status_code: int, reason: str) -> None:
        self.status_code = status_code
        self.reason = reason
        super().__init__(f"YouTube API request failed ({status_code}, {reason})")


class YouTubeConfigurationError(RuntimeError):
    pass


class YouTubeInvalidAPIKey(YouTubeAPIError):
    pass


class YouTubeQuotaExceeded(YouTubeAPIError):
    pass


class YouTubeRateLimited(YouTubeAPIError):
    pass


class YouTubeCommentsUnavailable(YouTubeAPIError):
    pass


class YouTubeVideoUnavailable(YouTubeAPIError):
    pass


class YouTubeDataSource(HttpSource):
    source_name = "youtube"
    api_root = "https://www.googleapis.com/youtube/v3"
    quota_reasons = {"quotaExceeded", "dailyLimitExceeded"}
    rate_limit_reasons = {"rateLimitExceeded", "userRateLimitExceeded"}

    def __init__(
        self,
        api_key: SecretStr | None,
        *,
        max_videos_per_search: int = 5,
        comments_per_video: int = 20,
        max_comment_pages_per_video: int = 1,
        **http_options: Any,
    ) -> None:
        if not 1 <= max_videos_per_search <= 50:
            raise ValueError("max_videos_per_search must be between 1 and 50")
        if not 1 <= comments_per_video <= 100:
            raise ValueError("comments_per_video must be between 1 and 100")
        if max_comment_pages_per_video < 1:
            raise ValueError("max_comment_pages_per_video must be positive")
        self._api_key = api_key
        self.max_videos_per_search = max_videos_per_search
        self.comments_per_video = comments_per_video
        self.max_comment_pages_per_video = max_comment_pages_per_video
        super().__init__(**http_options)

    @property
    def enabled(self) -> bool:
        return bool(self._api_key and self._api_key.get_secret_value().strip())

    @property
    def disabled_message(self) -> str:
        return "YouTube source disabled"

    def health_check(self) -> bool:
        payload = self._api_get(
            "search",
            {
                "part": "snippet",
                "type": "video",
                "q": "youtube api health check",
                "maxResults": 1,
                "fields": "items(id/videoId)",
            },
        )
        if not isinstance(payload.get("items"), list):
            raise MalformedSourceResponse("YouTube health response did not contain an items list")
        return True

    def search(self, keyword: str, limit: int) -> list[RawMention]:
        if limit < 1:
            raise ValueError("limit must be positive")
        video_limit = min(limit, self.max_videos_per_search, 50)
        search_payload = self._api_get(
            "search",
            {
                "part": "snippet",
                "type": "video",
                "q": keyword,
                "maxResults": video_limit,
                "fields": "items(id/videoId),nextPageToken",
            },
        )
        search_items = search_payload.get("items")
        if not isinstance(search_items, list):
            raise MalformedSourceResponse("YouTube search response did not contain an items list")

        video_ids: list[str] = []
        seen_video_ids: set[str] = set()
        for item in search_items:
            video_id = item.get("id", {}).get("videoId") if isinstance(item, dict) else None
            if isinstance(video_id, str) and video_id not in seen_video_ids:
                seen_video_ids.add(video_id)
                video_ids.append(video_id)
            if len(video_ids) >= video_limit:
                break
        if not video_ids:
            return []

        video_payload = self._api_get(
            "videos",
            {
                "part": "snippet,statistics",
                "id": ",".join(video_ids),
                "fields": (
                    "items(id,snippet(title,description,channelTitle,publishedAt),"
                    "statistics(viewCount,likeCount,commentCount))"
                ),
            },
        )
        video_items = video_payload.get("items")
        if not isinstance(video_items, list):
            raise MalformedSourceResponse("YouTube videos response did not contain an items list")

        videos: list[tuple[str, dict[str, Any], str]] = []
        mentions: list[RawMention] = []
        for video in video_items:
            if not isinstance(video, dict) or not isinstance(video.get("id"), str):
                continue
            video_id = video["id"]
            snippet = video.get("snippet")
            if not isinstance(snippet, dict):
                snippet = {}
            statistics = video.get("statistics")
            if not isinstance(statistics, dict):
                statistics = {}
            title = _optional_str(snippet.get("title"))
            engagement = _engagement(
                statistics,
                {"views": "viewCount", "likes": "likeCount", "comments": "commentCount"},
            )
            mentions.append(
                RawMention(
                    external_id=f"video:{video_id}",
                    title=title,
                    content=_optional_str(snippet.get("description")),
                    author=_optional_str(snippet.get("channelTitle")),
                    url=f"https://www.youtube.com/watch?v={video_id}",
                    published_at=_optional_str(snippet.get("publishedAt")),
                    engagement=engagement or None,
                )
            )
            videos.append((video_id, snippet, title or video_id))

        for video_id, snippet, title in videos:
            try:
                mentions.extend(self._video_comments(video_id, title))
            except YouTubeQuotaExceeded as error:
                logger.warning(
                    "youtube.comments.stopped_quota",
                    extra={"video_id": video_id, "error_reason": error.reason},
                )
                break
            except YouTubeInvalidAPIKey:
                raise
            except YouTubeAPIError as error:
                logger.warning(
                    "youtube.comments.unavailable",
                    extra={"video_id": video_id, "error_reason": error.reason},
                )
        return mentions

    def _video_comments(self, video_id: str, video_title: str) -> list[RawMention]:
        comments: list[RawMention] = []
        seen_comment_ids: set[str] = set()
        page_token: str | None = None
        for _ in range(self.max_comment_pages_per_video):
            params: dict[str, Any] = {
                "part": "snippet",
                "videoId": video_id,
                "maxResults": self.comments_per_video,
                "textFormat": "plainText",
            }
            if page_token:
                params["pageToken"] = page_token
            payload = self._api_get("commentThreads", params)
            items = payload.get("items")
            if not isinstance(items, list):
                raise MalformedSourceResponse("YouTube comments response did not contain an items list")

            for thread in items:
                if not isinstance(thread, dict):
                    continue
                thread_snippet = thread.get("snippet")
                if not isinstance(thread_snippet, dict):
                    continue
                comment = thread_snippet.get("topLevelComment")
                if not isinstance(comment, dict):
                    continue
                comment_id = comment.get("id")
                comment_snippet = comment.get("snippet")
                if not isinstance(comment_id, str) or not isinstance(comment_snippet, dict):
                    continue
                if comment_id in seen_comment_ids:
                    continue
                seen_comment_ids.add(comment_id)

                engagement = _engagement(
                    comment_snippet,
                    {"likes": "likeCount"},
                )
                reply_count = _optional_int(thread_snippet.get("totalReplyCount"))
                if reply_count is not None:
                    engagement["replies"] = reply_count
                comments.append(
                    RawMention(
                        external_id=f"comment:{comment_id}",
                        title=f"Comment on: {video_title}",
                        content=_optional_str(
                            comment_snippet.get("textOriginal") or comment_snippet.get("textDisplay")
                        ),
                        author=_optional_str(comment_snippet.get("authorDisplayName")),
                        url=(
                            f"https://www.youtube.com/watch?v={video_id}"
                            f"&lc={quote(comment_id, safe='')}"
                        ),
                        published_at=_optional_str(comment_snippet.get("publishedAt")),
                        engagement=engagement or None,
                    )
                )

            page_token = payload.get("nextPageToken")
            if not isinstance(page_token, str) or not page_token:
                break
        return comments

    def _api_get(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if self._api_key is None or not self._api_key.get_secret_value():
            raise YouTubeConfigurationError("YOUTUBE_API_KEY is not configured")

        request_params = {**params, "key": self._api_key.get_secret_value()}
        for attempt in range(self.max_retries + 1):
            response = self._get(
                f"{self.api_root}/{method}",
                params=request_params,
                allow_error_status=True,
            )
            payload = _json_object(response)
            if response.is_success:
                return payload

            reason, message = _api_error_details(payload)
            if response.status_code == 429 and reason == "unknownError":
                reason = "rateLimitExceeded"
            message_lower = message.casefold()
            if reason == "keyInvalid" or "api key not valid" in message_lower:
                raise YouTubeInvalidAPIKey(response.status_code, reason)
            if reason in self.quota_reasons:
                raise YouTubeQuotaExceeded(response.status_code, reason)
            if reason in self.rate_limit_reasons:
                if attempt < self.max_retries:
                    self._sleep(self.backoff_seconds * (2**attempt))
                    continue
                raise YouTubeRateLimited(response.status_code, reason)
            if reason == "commentsDisabled" or (
                method == "commentThreads" and reason == "forbidden"
            ):
                raise YouTubeCommentsUnavailable(response.status_code, reason)
            if reason == "videoNotFound":
                raise YouTubeVideoUnavailable(response.status_code, reason)
            raise YouTubeAPIError(response.status_code, reason)

        raise YouTubeAPIError(429, "rateLimitExceeded")


def _json_object(response: httpx.Response) -> dict[str, Any]:
    try:
        payload: Any = response.json()
    except ValueError as error:
        raise MalformedSourceResponse("YouTube returned invalid JSON") from error
    if not isinstance(payload, dict):
        raise MalformedSourceResponse("YouTube returned an unexpected JSON structure")
    return payload


def _api_error_details(payload: dict[str, Any]) -> tuple[str, str]:
    error = payload.get("error")
    if not isinstance(error, dict):
        return "unknownError", ""
    errors = error.get("errors")
    reason = "unknownError"
    if isinstance(errors, list) and errors and isinstance(errors[0], dict):
        reason = _optional_str(errors[0].get("reason")) or reason
    return reason, _optional_str(error.get("message")) or ""


def _engagement(source: dict[str, Any], mapping: dict[str, str]) -> dict[str, int]:
    metrics: dict[str, int] = {}
    for output_key, input_key in mapping.items():
        value = _optional_int(source.get(input_key))
        if value is not None:
            metrics[output_key] = value
    return metrics


def _optional_int(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError, OverflowError):
        return None


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None