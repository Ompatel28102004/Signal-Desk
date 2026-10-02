from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from backend.app.ai.models import AIInsights
from backend.app.ingestion.models import SourceFailure


Keyword = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
SourceOption = Literal["hacker_news", "rss", "youtube"]
Sentiment = Literal["Positive", "Neutral", "Negative"]
Topic = Literal[
    "Product",
    "Pricing",
    "Customer Service",
    "Quality",
    "Competitors",
    "Complaints",
    "Features",
    "Other",
]


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    keyword: Keyword
    sources: list[SourceOption] | None = Field(default=None, min_length=1)
    limit: int = Field(default=50, ge=1, le=100)


class CollectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    keyword: Keyword
    limit: int = Field(default=50, ge=1, le=100)


class MentionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID | None = None
    source: str
    external_id: str
    keyword: str
    title: str | None = None
    content: str | None = None
    author: str | None = None
    url: str | None = None
    published_at: datetime | None = None
    collected_at: datetime | None = None
    engagement: dict[str, int | float | str] | None = None
    normalized_text: str | None = None
    content_hash: str | None = None
    relevance_score: float | None = None
    relevance_reason: str | None = None
    sentiment: Sentiment | None = None
    sentiment_score: float | None = None
    topic: Topic | None = None
    topic_score: float | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class SearchResponse(BaseModel):
    keyword: str
    total: int
    partial_success: bool
    mentions: list[MentionResponse]
    source_failures: list[SourceFailure]
    disabled_sources: list[str]


class Pagination(BaseModel):
    page: int
    page_size: int
    total: int
    pages: int


class MentionPageResponse(BaseModel):
    items: list[MentionResponse]
    pagination: Pagination


class CountItem(BaseModel):
    name: str
    count: int


class TimeSeriesItem(BaseModel):
    bucket: datetime
    count: int


class AnalyticsResponse(BaseModel):
    keyword: str | None
    days: int
    total: int
    sentiment_distribution: dict[str, int]
    topics: list[CountItem]
    time_series: list[TimeSeriesItem]


class TopicTrend(BaseModel):
    topic: str
    current_count: int
    previous_count: int
    change_percent: float | None
    new_topic: bool
    increased: bool


class TrendsResponse(BaseModel):
    keyword: str
    period_days: int
    trends: list[TopicTrend]


class NegativeSpikeResponse(BaseModel):
    keyword: str
    detected: bool
    window_days: int
    current_total: int
    current_negative: int
    current_negative_rate: float
    previous_total: int
    previous_negative: int
    previous_negative_rate: float
    rate_change_percentage_points: float
    baseline_available: bool


class CompetitorSentiment(BaseModel):
    positive: int
    neutral: int
    negative: int
    unclassified: int


class CompetitorTopic(BaseModel):
    topic: str
    count: int


class CompetitorComplaint(BaseModel):
    text: str
    count: int


class CompetitorItem(BaseModel):
    brand: Literal["Toyota", "Hyundai", "Kia"]
    mention_volume: int
    sentiment_distribution: CompetitorSentiment
    topics: list[CompetitorTopic]
    common_complaints: list[CompetitorComplaint]


class CompetitorComparisonResponse(BaseModel):
    days: int
    competitors: list[CompetitorItem]


class SourceStatus(BaseModel):
    name: str
    status: Literal["configured", "disabled", "not_configured"]
    enabled: bool
    configured_items: int | None = None
    detail: str


class SourcesResponse(BaseModel):
    sources: list[SourceStatus]


class InsightsResponse(BaseModel):
    keyword: str
    mentions_analyzed: int
    insights: AIInsights


class CollectResponse(BaseModel):
    keyword: str
    collected: int
    inserted: int
    already_present: int
    classified: int
    partial_success: bool
    source_failures: list[SourceFailure]
    disabled_sources: list[str]
    mentions: list[MentionResponse]
    insights: AIInsights