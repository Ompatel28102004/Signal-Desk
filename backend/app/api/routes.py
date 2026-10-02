import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.app.ai.service import AIInsightsService
from backend.app.api.dependencies import (
    get_ai_insights_service,
    get_database_session,
    get_ingestion_manager,
)
from backend.app.api.schemas import (
    AnalyticsResponse,
    CollectRequest,
    CollectResponse,
    CompetitorComparisonResponse,
    CompetitorComplaint,
    CompetitorItem,
    CompetitorSentiment,
    CompetitorTopic,
    InsightsResponse,
    MentionPageResponse,
    MentionResponse,
    Pagination,
    SearchRequest,
    SearchResponse,
    SourcesResponse,
    NegativeSpikeResponse,
    TopicTrend,
    TrendsResponse,
)
from backend.app.api.service import (
    analytics_response_data,
    collect_and_summarize,
    source_statuses,
    summarize_stored_mentions,
)
from backend.app.config import settings
from backend.app.ingestion.manager import IngestionManager
from backend.app.ingestion.sources import build_ingestion_manager
from backend.app.repositories import mentions as mention_repository


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


@router.post("/search", response_model=SearchResponse)
def search_mentions(request: SearchRequest) -> SearchResponse:
    try:
        manager = build_ingestion_manager(
            settings,
            source_names=set(request.sources) if request.sources is not None else None,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    result = manager.search(request.keyword, request.limit)
    return SearchResponse(
        keyword=request.keyword,
        total=len(result.mentions),
        partial_success=bool(result.failures or result.disabled_sources),
        mentions=[MentionResponse.model_validate(item.model_dump()) for item in result.mentions],
        source_failures=result.failures,
        disabled_sources=result.disabled_sources,
    )


@router.post("/collect", response_model=CollectResponse)
def collect_mentions(
    request: CollectRequest,
    session: Session = Depends(get_database_session),
    manager: IngestionManager = Depends(get_ingestion_manager),
    insights_service: AIInsightsService = Depends(get_ai_insights_service),
) -> CollectResponse:
    try:
        return collect_and_summarize(
            session,
            manager,
            insights_service,
            keyword=request.keyword,
            limit=request.limit,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail="Collection request is invalid") from error


@router.get("/mentions", response_model=MentionPageResponse)
def get_mentions(
    source: str | None = None,
    keyword: str | None = None,
    sentiment: str | None = Query(default=None, pattern="^(Positive|Neutral|Negative)$"),
    topic: str | None = None,
    search: str | None = Query(default=None, max_length=255),
    published_after: datetime | None = None,
    published_before: datetime | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
    session: Session = Depends(get_database_session),
) -> MentionPageResponse:
    if published_after and published_before and published_after > published_before:
        raise HTTPException(status_code=422, detail="published_after must not be later than published_before")
    rows, total = mention_repository.list_mentions_page(
        session,
        source=source,
        keyword=keyword,
        sentiment=sentiment,
        topic=topic,
        search=search,
        published_after=published_after,
        published_before=published_before,
        limit=page_size,
        offset=(page - 1) * page_size,
    )
    return MentionPageResponse(
        items=[MentionResponse.model_validate(row, from_attributes=True) for row in rows],
        pagination=Pagination(
            page=page,
            page_size=page_size,
            total=total,
            pages=(total + page_size - 1) // page_size,
        ),
    )


@router.get("/mentions/{mention_id}", response_model=MentionResponse)
def get_mention(
    mention_id: str,
    session: Session = Depends(get_database_session),
) -> MentionResponse:
    from uuid import UUID

    try:
        parsed_id = UUID(mention_id)
    except ValueError as error:
        raise HTTPException(status_code=422, detail="mention_id must be a UUID") from error
    mention = mention_repository.get_by_id(session, parsed_id)
    if mention is None:
        raise HTTPException(status_code=404, detail="Mention not found")
    return MentionResponse.model_validate(mention, from_attributes=True)


@router.get("/analytics", response_model=AnalyticsResponse)
def get_analytics(
    keyword: str | None = Query(default=None, max_length=255),
    days: int = Query(default=30, ge=1, le=365),
    session: Session = Depends(get_database_session),
) -> AnalyticsResponse:
    try:
        return AnalyticsResponse.model_validate(
            analytics_response_data(session, keyword=keyword, days=days)
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail="Analytics filter is invalid") from error


@router.get("/analytics/trends", response_model=TrendsResponse)
def get_topic_trends(
    keyword: str = Query(min_length=1, max_length=255),
    period_days: int = Query(default=7, ge=1, le=90),
    session: Session = Depends(get_database_session),
) -> TrendsResponse:
    trends = mention_repository.get_topic_trends(
        session,
        keyword=keyword.strip(),
        period_days=period_days,
    )
    return TrendsResponse(
        keyword=keyword.strip(),
        period_days=period_days,
        trends=[TopicTrend.model_validate(item) for item in trends],
    )


@router.get("/alerts/negative-spike", response_model=NegativeSpikeResponse)
def get_negative_spike(
    keyword: str = Query(min_length=1, max_length=255),
    window_days: int = Query(default=7, ge=1, le=90),
    session: Session = Depends(get_database_session),
) -> NegativeSpikeResponse:
    result = mention_repository.get_negative_sentiment_spike(
        session,
        keyword=keyword.strip(),
        window_days=window_days,
    )
    return NegativeSpikeResponse(keyword=keyword.strip(), **result)


@router.get("/competitors", response_model=CompetitorComparisonResponse)
def get_competitor_comparison(
    days: int = Query(default=30, ge=1, le=365),
    session: Session = Depends(get_database_session),
) -> CompetitorComparisonResponse:
    records = mention_repository.get_competitor_comparison(
        session,
        brands=("Toyota", "Hyundai", "Kia"),
        days=days,
    )
    competitors = []
    for record in records:
        sentiments = record["sentiment_distribution"]
        competitors.append(
            CompetitorItem(
                brand=record["brand"],
                mention_volume=record["mention_volume"],
                sentiment_distribution=CompetitorSentiment(
                    positive=sentiments.get("Positive", 0),
                    neutral=sentiments.get("Neutral", 0),
                    negative=sentiments.get("Negative", 0),
                    unclassified=sentiments.get("Unclassified", 0),
                ),
                topics=[CompetitorTopic.model_validate(item) for item in record["topics"]],
                common_complaints=[
                    CompetitorComplaint.model_validate(item)
                    for item in record["common_complaints"]
                ],
            )
        )
    return CompetitorComparisonResponse(days=days, competitors=competitors)


@router.get("/insights", response_model=InsightsResponse)
def get_insights(
    keyword: str = Query(min_length=1, max_length=255),
    limit: int = Query(default=500, ge=1, le=500),
    session: Session = Depends(get_database_session),
    insights_service: AIInsightsService = Depends(get_ai_insights_service),
) -> InsightsResponse:
    insights, rows = summarize_stored_mentions(
        session,
        insights_service,
        keyword=keyword.strip(),
        limit=limit,
    )
    return InsightsResponse(keyword=keyword.strip(), mentions_analyzed=len(rows), insights=insights)


@router.get("/sources", response_model=SourcesResponse)
def get_sources() -> SourcesResponse:
    return SourcesResponse(sources=source_statuses(settings))