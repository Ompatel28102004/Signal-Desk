from datetime import UTC, datetime

import httpx
import pytest
from pydantic import SecretStr

from backend.app.config import Settings
from backend.app.ingestion.sources import build_ingestion_manager
from backend.app.ingestion.sources.youtube import (
    YouTubeConfigurationError,
    YouTubeDataSource,
    YouTubeInvalidAPIKey,
    YouTubeQuotaExceeded,
)


API_KEY = SecretStr("test-api-key")


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _search_response(request: httpx.Request, *video_ids: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={"items": [{"id": {"videoId": video_id}} for video_id in video_ids]},
        request=request,
    )


def _video_response(request: httpx.Request, *video_ids: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "items": [
                {
                    "id": video_id,
                    "snippet": {
                        "title": f"Title {video_id}",
                        "description": "A video description",
                        "channelTitle": "Example channel",
                        "publishedAt": "2025-01-02T03:04:05Z",
                    },
                    "statistics": {
                        "viewCount": "1200",
                        "likeCount": "57",
                        "commentCount": "19",
                    },
                }
                for video_id in video_ids
            ]
        },
        request=request,
    )


def test_youtube_batches_video_details_and_pages_comments() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/search"):
            return _search_response(request, "video-1")
        if request.url.path.endswith("/videos"):
            return _video_response(request, "video-1")
        if request.url.path.endswith("/commentThreads"):
            if request.url.params.get("pageToken") == "next-page":
                threads = [
                    {
                        "snippet": {
                            "topLevelComment": {
                                "id": "comment-2",
                                "snippet": {
                                    "textDisplay": "Second comment",
                                    "authorDisplayName": "Bea",
                                    "publishedAt": "2025-01-03T00:00:00Z",
                                    "likeCount": 3,
                                },
                            }
                        }
                    }
                ]
                return httpx.Response(200, json={"items": threads}, request=request)
            threads = [
                {
                    "snippet": {
                        "totalReplyCount": 2,
                        "topLevelComment": {
                            "id": "comment-1",
                            "snippet": {
                                "textOriginal": "First comment",
                                "authorDisplayName": "Ada",
                                "publishedAt": "2025-01-02T04:00:00Z",
                                "likeCount": 7,
                            },
                        },
                    }
                },
            ]
            return httpx.Response(
                200,
                json={"items": threads, "nextPageToken": "next-page"},
                request=request,
            )
        raise AssertionError(f"Unexpected endpoint: {request.url.path}")

    source = YouTubeDataSource(
        API_KEY,
        client=_client(handler),
        max_videos_per_search=3,
        comments_per_video=2,
        max_comment_pages_per_video=2,
    )

    mentions = source.search("topic", limit=3)

    assert len(requests) == 4
    assert requests[0].url.params["maxResults"] == "3"
    assert requests[1].url.params["id"] == "video-1"
    assert requests[1].url.params["id"].count(",") == 0
    assert requests[2].url.params["maxResults"] == "2"
    assert requests[3].url.params["pageToken"] == "next-page"
    assert all(request.url.params["key"] == API_KEY.get_secret_value() for request in requests)
    assert [mention.external_id for mention in mentions] == [
        "video:video-1",
        "comment:comment-1",
        "comment:comment-2",
    ]
    assert mentions[0].engagement == {"views": 1200, "likes": 57, "comments": 19}
    assert mentions[1].engagement == {"likes": 7, "replies": 2}
    assert mentions[1].author == "Ada"
    assert mentions[1].published_at == datetime(2025, 1, 2, 4, tzinfo=UTC)


def test_youtube_comments_disabled_keeps_video_mention() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/search"):
            return _search_response(request, "video-1")
        if request.url.path.endswith("/videos"):
            return _video_response(request, "video-1")
        return httpx.Response(
            403,
            json={
                "error": {
                    "code": 403,
                    "errors": [{"reason": "commentsDisabled"}],
                }
            },
            request=request,
        )

    source = YouTubeDataSource(API_KEY, client=_client(handler), max_retries=0)

    mentions = source.search("topic", limit=1)

    assert [mention.external_id for mention in mentions] == ["video:video-1"]


def test_youtube_quota_error_stops_comments_but_keeps_selected_videos() -> None:
    comment_requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal comment_requests
        if request.url.path.endswith("/search"):
            return _search_response(request, "video-1", "video-2")
        if request.url.path.endswith("/videos"):
            return _video_response(request, "video-1", "video-2")
        comment_requests += 1
        return httpx.Response(
            403,
            json={
                "error": {
                    "code": 403,
                    "errors": [{"reason": "quotaExceeded"}],
                }
            },
            request=request,
        )

    source = YouTubeDataSource(API_KEY, client=_client(handler), max_retries=0)

    mentions = source.search("topic", limit=2)

    assert [mention.external_id for mention in mentions] == ["video:video-1", "video:video-2"]
    assert comment_requests == 1


def test_youtube_invalid_key_is_classified_without_leaking_key() -> None:
    client = _client(
        lambda request: httpx.Response(
            400,
            json={"error": {"code": 400, "errors": [{"reason": "keyInvalid"}]}},
            request=request,
        )
    )

    with pytest.raises(YouTubeInvalidAPIKey) as error:
        YouTubeDataSource(API_KEY, client=client, max_retries=0).search("topic", limit=1)

    assert API_KEY.get_secret_value() not in str(error.value)


def test_youtube_quota_error_during_search_is_classified() -> None:
    client = _client(
        lambda request: httpx.Response(
            403,
            json={"error": {"code": 403, "errors": [{"reason": "quotaExceeded"}]}},
            request=request,
        )
    )

    with pytest.raises(YouTubeQuotaExceeded):
        YouTubeDataSource(API_KEY, client=client, max_retries=0).search("topic", limit=1)


def test_youtube_retries_rate_limit_once_with_backoff() -> None:
    calls = 0
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                429,
                json={"error": {"errors": [{"reason": "rateLimitExceeded"}]}},
                request=request,
            )
        return httpx.Response(200, json={"items": []}, request=request)

    source = YouTubeDataSource(
        API_KEY,
        client=_client(handler),
        max_retries=1,
        backoff_seconds=0.1,
        sleep=sleeps.append,
    )

    assert source.search("topic", limit=1) == []
    assert calls == 2
    assert sleeps == [0.1]


def test_youtube_unavailable_video_is_skipped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/search"):
            return _search_response(request, "removed-video")
        return httpx.Response(200, json={"items": []}, request=request)

    mentions = YouTubeDataSource(API_KEY, client=_client(handler)).search("topic", limit=1)

    assert mentions == []


def test_youtube_empty_search_uses_only_one_request() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"items": []}, request=request)

    mentions = YouTubeDataSource(API_KEY, client=_client(handler)).search("topic", limit=1)

    assert mentions == []
    assert len(requests) == 1


def test_youtube_requires_environment_backed_key() -> None:
    source = YouTubeDataSource(None, client=_client(lambda request: pytest.fail("unexpected request")))

    with pytest.raises(YouTubeConfigurationError):
        source.health_check()


def test_configured_manager_registers_youtube_only_with_key() -> None:
    config = Settings(_env_file=None, youtube_api_key=API_KEY)

    manager = build_ingestion_manager(config)

    assert [source.source_name for source in manager._sources] == [
        "hacker_news",
        "youtube",
    ]
    assert manager._sources[-1].enabled is True


def test_configured_manager_ignores_blank_youtube_key() -> None:
    config = Settings(_env_file=None, youtube_api_key=SecretStr(""))

    manager = build_ingestion_manager(config)

    assert [source.source_name for source in manager._sources] == [
        "hacker_news",
        "youtube",
    ]
    assert manager._sources[1].enabled is False
