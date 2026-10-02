from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


SourceText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
ExternalId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=512)]
Keyword = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]


class MentionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: SourceText
    external_id: ExternalId
    keyword: Keyword
    title: str | None = None
    content: str | None = None
    author: str | None = None
    url: str | None = None
    published_at: datetime | None = None
    engagement: dict[str, Any] | None = None
    normalized_text: str | None = None
    content_hash: Annotated[str | None, Field(min_length=1, max_length=64)] = None
    relevance_score: float | None = None
    relevance_reason: str | None = None
    sentiment: Annotated[str | None, Field(max_length=32)] = None
    sentiment_score: float | None = None
    topic: Annotated[str | None, Field(max_length=255)] = None
    topic_score: float | None = None