from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from backend.app.ai.models import AIInsights
from backend.app.ai.service import AIInsightsService
from backend.app.api.schemas import (
    CollectResponse,
    CountItem,
    MentionResponse,
    SourceStatus,
    TimeSeriesItem,
)
from backend.app.config import Settings, settings
from backend.app.ingestion.manager import IngestionManager
from backend.app.ingestion.models import IngestionResult, NormalizedMention
from backend.app.models import Mention
from backend.app.repositories import mentions as mention_repository
from backend.app.schemas.mention import MentionCreate


def source_statuses(config: Settings = settings) -> list[SourceStatus]:
    youtube_enabled = bool(
        config.youtube_api_key and config.youtube_api_key.get_secret_value().strip()
    )
    return [
        SourceStatus(
            name="hacker_news",
            status="configured",
            enabled=True,
            detail="Keyless public search; network availability is checked per request.",
        ),
        SourceStatus(
            name="rss",
            status="configured" if config.rss_feed_urls else "not_configured",
            enabled=bool(config.rss_feed_urls),
            configured_items=len(config.rss_feed_urls),
            detail="Configured feeds are queried independently.",
        ),
        SourceStatus(
            name="youtube",
            status="configured" if youtube_enabled else "disabled",
            enabled=youtube_enabled,
            detail="API key configuration only; live API status is checked during search.",
        ),
    ]


def collect_and_summarize(
    session: Session,
    manager: IngestionManager,
    insights_service: AIInsightsService,
    *,
    keyword: str,
    limit: int,
) -> CollectResponse:
    outcome = collect_and_persist(session, manager, keyword=keyword, limit=limit)
    insights: AIInsights = insights_service.summarize(keyword, outcome.classified_mentions)
    return CollectResponse(
        keyword=keyword,
        collected=len(outcome.ingestion.mentions),
        inserted=outcome.inserted,
        already_present=len(outcome.stored_rows) - outcome.inserted,
        classified=len(outcome.classified_mentions),
        partial_success=bool(outcome.ingestion.failures or outcome.ingestion.disabled_sources),
        source_failures=outcome.ingestion.failures,
        disabled_sources=outcome.ingestion.disabled_sources,
        mentions=[
            MentionResponse.model_validate(row, from_attributes=True)
            for row in outcome.stored_rows
        ],
        insights=insights,
    )


@dataclass
class CollectionOutcome:
    ingestion: IngestionResult
    stored_rows: list[Mention]
    inserted: int
    classified_mentions: list[NormalizedMention]


def collect_and_persist(
    session: Session,
    manager: IngestionManager,
    *,
    keyword: str,
    limit: int,
) -> CollectionOutcome:
    ingestion = manager.search(keyword, limit, classify=False)
    stored_rows: list[Mention] = []
    inserted = 0
    for cleaned in ingestion.mentions:
        payload = MentionCreate.model_validate(cleaned.model_dump(exclude={"collected_at"}))
        row, was_inserted = mention_repository.add_or_get(session, payload)
        stored_rows.append(row)
        inserted += int(was_inserted)

    if stored_rows:
        session.commit()

    persisted_mentions = [_as_normalized(row) for row in stored_rows]
    classified_mentions = manager.classify_many(persisted_mentions)
    for row, classified in zip(stored_rows, classified_mentions, strict=True):
        row.sentiment = classified.sentiment
        row.sentiment_score = classified.sentiment_score
        row.topic = classified.topic
        row.topic_score = classified.topic_score
    if stored_rows:
        session.commit()

    return CollectionOutcome(
        ingestion=ingestion,
        stored_rows=stored_rows,
        inserted=inserted,
        classified_mentions=classified_mentions,
    )


def analytics_response_data(
    session: Session,
    *,
    keyword: str | None,
    days: int,
) -> dict[str, object]:
    since = datetime.now(UTC) - timedelta(days=days)
    data = mention_repository.get_analytics(session, keyword=keyword, since=since)
    return {
        "keyword": keyword,
        "days": days,
        "total": data["total"],
        "sentiment_distribution": data["sentiment_distribution"],
        "topics": [CountItem(name=item["topic"], count=item["count"]) for item in data["topics"]],
        "time_series": [
            TimeSeriesItem(bucket=item["bucket"], count=item["count"])
            for item in data["time_series"]
        ],
    }


def summarize_stored_mentions(
    session: Session,
    insights_service: AIInsightsService,
    *,
    keyword: str,
    limit: int,
) -> tuple[AIInsights, Sequence[Mention]]:
    rows = mention_repository.list_mentions(
        session,
        keyword=keyword,
        limit=limit,
        offset=0,
    )
    return insights_service.summarize(keyword, [_as_normalized(row) for row in rows]), rows


def _as_normalized(row: Mention) -> NormalizedMention:
    return NormalizedMention(
        source=row.source,
        external_id=row.external_id,
        keyword=row.keyword,
        title=row.title,
        content=row.content,
        author=row.author,
        url=row.url,
        published_at=row.published_at,
        collected_at=row.collected_at,
        engagement=row.engagement,
        normalized_text=row.normalized_text,
        content_hash=row.content_hash,
        relevance_score=row.relevance_score,
        relevance_reason=row.relevance_reason,
        sentiment=row.sentiment,
        sentiment_score=row.sentiment_score,
        topic=row.topic,
        topic_score=row.topic_score,
    )