from datetime import UTC, datetime
from html import unescape
from typing import Any

from backend.app.ingestion.http import HttpSource, MalformedSourceResponse
from backend.app.ingestion.models import RawMention
from backend.app.ingestion.text import html_to_text


class HackerNewsSource(HttpSource):
    source_name = "hacker_news"
    endpoint = "https://hn.algolia.com/api/v1/search_by_date"

    def search(self, keyword: str, limit: int) -> list[RawMention]:
        if limit < 1:
            raise ValueError("limit must be positive")
        response = self._get(self.endpoint, params={"query": keyword, "hitsPerPage": min(limit, 100)})
        try:
            payload: Any = response.json()
        except ValueError as error:
            raise MalformedSourceResponse("Hacker News returned invalid JSON") from error
        if not isinstance(payload, dict) or not isinstance(payload.get("hits"), list):
            raise MalformedSourceResponse("Hacker News response did not contain a hits list")

        mentions: list[RawMention] = []
        seen_ids: set[str] = set()
        for hit in payload["hits"]:
            if not isinstance(hit, dict):
                continue
            external_id = hit.get("objectID") or hit.get("story_id")
            if external_id is None:
                continue
            external_id = str(external_id)
            if external_id in seen_ids:
                continue
            seen_ids.add(external_id)

            title = html_to_text(hit.get("story_title") or hit.get("title"))
            content = html_to_text(
                hit.get("comment_text") or hit.get("story_text") or hit.get("description")
            )
            url = hit.get("url") or f"https://news.ycombinator.com/item?id={external_id}"
            mentions.append(
                RawMention(
                    external_id=external_id,
                    title=unescape(title) if title else None,
                    content=unescape(content) if content else None,
                    author=hit.get("author"),
                    url=url,
                    published_at=_parse_datetime(hit.get("created_at"), hit.get("created_at_i")),
                )
            )
            if len(mentions) >= limit:
                break
        return mentions


def _parse_datetime(value: object, epoch: object) -> datetime | None:
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass
    if isinstance(epoch, (int, float)):
        try:
            return datetime.fromtimestamp(epoch, tz=UTC)
        except (OverflowError, OSError, ValueError):
            pass
    return None