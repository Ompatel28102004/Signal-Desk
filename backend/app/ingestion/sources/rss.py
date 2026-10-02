import hashlib
import re
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from time import struct_time
from urllib.parse import urlsplit

import feedparser

from backend.app.ingestion.http import HttpSource, MalformedSourceResponse
from backend.app.ingestion.models import RawMention
from backend.app.ingestion.text import html_to_text


class RSSFeedSource(HttpSource):
    def __init__(self, feed_url: str, **options: object) -> None:
        parsed_url = urlsplit(str(feed_url))
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.hostname:
            raise ValueError("feed_url must be an absolute HTTP(S) URL")
        self.feed_url = str(feed_url)
        host = parsed_url.hostname[:54]
        suffix = hashlib.sha256(self.feed_url.encode("utf-8")).hexdigest()[:12]
        self._source_name = f"rss:{host}:{suffix}"
        super().__init__(**options)

    @property
    def source_name(self) -> str:
        return self._source_name

    def search(self, keyword: str, limit: int) -> list[RawMention]:
        if limit < 1:
            raise ValueError("limit must be positive")
        response = self._get(self.feed_url)
        parsed_feed = feedparser.parse(response.content)
        entries = parsed_feed.get("entries")
        if not isinstance(entries, list):
            raise MalformedSourceResponse("RSS response did not contain an entries list")
        if parsed_feed.get("bozo") and not entries:
            raise MalformedSourceResponse("RSS response could not be parsed")

        keyword_tokens = re.findall(r"\w+", keyword.casefold())
        mentions: list[RawMention] = []
        seen_ids: set[str] = set()
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            title = html_to_text(entry.get("title"))
            content = _entry_content(entry)
            searchable_text = f"{title or ''} {content or ''}".casefold()
            if keyword_tokens and not all(token in searchable_text for token in keyword_tokens):
                continue

            link = entry.get("link")
            identity = entry.get("id") or entry.get("guid") or link
            if identity is None:
                identity = hashlib.sha256(searchable_text.encode("utf-8")).hexdigest()
            external_id = str(identity)
            if len(external_id) > 512:
                external_id = hashlib.sha256(external_id.encode("utf-8")).hexdigest()
            if external_id in seen_ids:
                continue
            seen_ids.add(external_id)

            author = entry.get("author")
            if not author and isinstance(entry.get("author_detail"), dict):
                author = entry["author_detail"].get("name")
            mentions.append(
                RawMention(
                    external_id=external_id,
                    title=title,
                    content=content,
                    author=author,
                    url=link,
                    published_at=_entry_datetime(entry),
                )
            )
            if len(mentions) >= limit:
                break
        return mentions


def _entry_content(entry: dict[str, object]) -> str | None:
    content_values = entry.get("content")
    if isinstance(content_values, list) and content_values:
        first_content = content_values[0]
        if isinstance(first_content, dict):
            content = html_to_text(first_content.get("value"))
            if content:
                return content
    return html_to_text(entry.get("summary") or entry.get("description"))


def _entry_datetime(entry: dict[str, object]) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        value = entry.get(key)
        if isinstance(value, struct_time):
            try:
                return datetime(*value[:6], tzinfo=UTC)
            except (TypeError, ValueError):
                pass
    for key in ("published", "updated", "date"):
        value = entry.get(key)
        if isinstance(value, str):
            try:
                return parsedate_to_datetime(value)
            except (TypeError, ValueError, OverflowError):
                pass
    return None