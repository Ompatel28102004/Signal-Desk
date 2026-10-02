from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=220)]
ProviderName = Literal["ollama", "gemini", "deterministic"]


class TopicCount(BaseModel):
    topic: str
    count: int = Field(ge=0)


class TopicSentimentCount(BaseModel):
    topic: str
    sentiment: str
    count: int = Field(ge=0)


class RepresentativeMention(BaseModel):
    title: str | None = Field(default=None, max_length=160)
    text: str = Field(max_length=280)


class InsightContext(BaseModel):
    """Small aggregate plus at most six bounded representative snippets."""

    model_config = ConfigDict(extra="forbid")

    keyword: str = Field(max_length=255)
    total_mentions: int = Field(ge=0)
    sentiment_distribution: dict[str, int]
    topic_distribution: list[TopicCount] = Field(max_length=8)
    topic_sentiment_distribution: list[TopicSentimentCount] = Field(max_length=24)
    common_themes: list[str] = Field(max_length=5)
    representative_positive: list[RepresentativeMention] = Field(max_length=3)
    representative_negative: list[RepresentativeMention] = Field(max_length=3)


class InsightContent(BaseModel):
    """Provider output validated against the same bounded JSON contract."""

    model_config = ConfigDict(extra="forbid")

    overall_discussion: ShortText
    common_themes: list[ShortText] = Field(max_length=4)
    positive_themes: list[ShortText] = Field(max_length=4)
    negative_themes: list[ShortText] = Field(max_length=4)
    common_complaints: list[ShortText] = Field(max_length=4)
    frequently_discussed_features: list[ShortText] = Field(max_length=4)
    opportunities: list[ShortText] = Field(max_length=4)


class AIInsights(InsightContent):
    provider: ProviderName
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))