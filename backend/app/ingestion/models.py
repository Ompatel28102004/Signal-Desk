import hashlib
import re
import unicodedata
from datetime import UTC, datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


SourceName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
ExternalId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=512)]
Keyword = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]


class RawMention(BaseModel):
    """Common adapter output; source-specific response data is optional and opaque."""

    model_config = ConfigDict(extra="forbid")

    external_id: ExternalId
    title: str | None = None
    content: str | None = None
    author: str | None = None
    url: str | None = None
    published_at: datetime | None = None
    engagement: dict[str, Any] | None = None
    source_data: dict[str, Any] | None = None


class NormalizedMention(BaseModel):
    """Provider-independent mention representation ready for persistence."""

    model_config = ConfigDict(extra="forbid")

    source: SourceName
    external_id: ExternalId
    keyword: Keyword
    title: str | None = None
    content: str | None = None
    author: str | None = None
    url: str | None = None
    published_at: datetime | None = None
    collected_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    engagement: dict[str, Any] | None = None
    normalized_text: str | None = None
    content_hash: Annotated[str | None, Field(min_length=1, max_length=64)] = None
    relevance_score: float | None = None
    relevance_reason: str | None = None
    sentiment: Annotated[str | None, Field(max_length=32)] = None
    sentiment_score: float | None = None
    topic: Annotated[str | None, Field(max_length=255)] = None
    topic_score: float | None = None


class SourceFailure(BaseModel):
    source: SourceName
    error_type: str


class IngestionResult(BaseModel):
    mentions: list[NormalizedMention] = Field(default_factory=list)
    failures: list[SourceFailure] = Field(default_factory=list)
    disabled_sources: list[str] = Field(default_factory=list)


def normalize_mention(source: str, keyword: str, raw: RawMention) -> NormalizedMention:
    normalized_title = _normalize_text(raw.title)
    normalized_content = _normalize_text(raw.content)
    text_parts = [part for part in (normalized_title, normalized_content) if part]
    normalized_text = "\n".join(text_parts) or None
    content_hash = (
        hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()
        if normalized_text is not None
        else None
    )

    return NormalizedMention(
        source=source,
        external_id=raw.external_id,
        keyword=keyword,
        title=raw.title,
        content=raw.content,
        author=raw.author,
        url=raw.url,
        published_at=_normalize_datetime(raw.published_at),
        engagement=raw.engagement,
        normalized_text=normalized_text,
        content_hash=content_hash,
    )


def _normalize_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _normalize_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = unicodedata.normalize("NFKC", value)
    normalized = re.sub(r"\s+", " ", normalized).strip().casefold()
    return normalized or None