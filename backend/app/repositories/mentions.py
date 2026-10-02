from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import Select, case, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from backend.app.models import Mention
from backend.app.schemas.mention import MentionCreate


def add_or_get(session: Session, mention: MentionCreate) -> tuple[Mention, bool]:
    statement = (
        insert(Mention)
        .values(**mention.model_dump())
        .on_conflict_do_nothing(constraint="uq_mentions_source_external_id")
        .returning(Mention)
    )
    inserted = session.scalars(statement).one_or_none()
    if inserted is not None:
        return inserted, True

    existing = get_by_source_external_id(session, mention.source, mention.external_id)
    if existing is None:
        raise RuntimeError("Conflicting mention was not visible after insert")
    return existing, False


def get_by_id(session: Session, mention_id: UUID) -> Mention | None:
    return session.get(Mention, mention_id)


def get_by_source_external_id(
    session: Session, source: str, external_id: str
) -> Mention | None:
    statement = select(Mention).where(
        Mention.source == source,
        Mention.external_id == external_id,
    )
    return session.scalar(statement)


def list_mentions(
    session: Session,
    *,
    source: str | None = None,
    keyword: str | None = None,
    sentiment: str | None = None,
    topic: str | None = None,
    published_after: datetime | None = None,
    published_before: datetime | None = None,
    search: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[Mention]:
    mentions, _ = list_mentions_page(
        session,
        source=source,
        keyword=keyword,
        sentiment=sentiment,
        topic=topic,
        published_after=published_after,
        published_before=published_before,
        search=search,
        limit=limit,
        offset=offset,
    )
    return mentions


def list_mentions_page(
    session: Session,
    *,
    source: str | None = None,
    keyword: str | None = None,
    sentiment: str | None = None,
    topic: str | None = None,
    published_after: datetime | None = None,
    published_before: datetime | None = None,
    search: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[Mention], int]:
    if not 1 <= limit <= 500:
        raise ValueError("limit must be between 1 and 500")
    if offset < 0:
        raise ValueError("offset must be non-negative")

    conditions = _mention_conditions(
        source=source,
        keyword=keyword,
        sentiment=sentiment,
        topic=topic,
        published_after=published_after,
        published_before=published_before,
        search=search,
    )
    total = session.scalar(select(func.count()).select_from(Mention).where(*conditions)) or 0
    statement: Select[tuple[Mention]] = select(Mention).where(*conditions)
    statement = statement.order_by(Mention.collected_at.desc(), Mention.id).limit(limit).offset(offset)
    return list(session.scalars(statement).all()), int(total)


def get_analytics(
    session: Session,
    *,
    keyword: str | None = None,
    since: datetime | None = None,
) -> dict[str, object]:
    conditions = _mention_conditions(keyword=keyword)
    event_time = func.coalesce(Mention.published_at, Mention.collected_at)
    if since is not None:
        conditions.append(event_time >= since)
    totals = int(session.scalar(select(func.count()).select_from(Mention).where(*conditions)) or 0)
    sentiment_rows = session.execute(
        select(Mention.sentiment, func.count())
        .where(*conditions)
        .group_by(Mention.sentiment)
        .order_by(func.count().desc())
    ).all()
    topic_rows = session.execute(
        select(Mention.topic, func.count())
        .where(*conditions)
        .group_by(Mention.topic)
        .order_by(func.count().desc())
    ).all()
    bucket = func.date_trunc("day", event_time).label("bucket")
    time_rows = session.execute(
        select(bucket, func.count())
        .where(*conditions)
        .group_by(bucket)
        .order_by(bucket.asc())
    ).all()
    return {
        "total": totals,
        "sentiment_distribution": {sentiment or "Unclassified": int(count) for sentiment, count in sentiment_rows},
        "topics": [{"topic": topic or "Other", "count": int(count)} for topic, count in topic_rows],
        "time_series": [
            {"bucket": timestamp, "count": int(count)} for timestamp, count in time_rows
        ],
    }


def get_topic_trends(
    session: Session,
    *,
    keyword: str,
    period_days: int = 7,
    now: datetime | None = None,
) -> list[dict[str, int | float | str | bool | None]]:
    if period_days < 1:
        raise ValueError("period_days must be positive")
    end = now or datetime.now(UTC)
    current_start = end - timedelta(days=period_days)
    previous_start = current_start - timedelta(days=period_days)
    event_time = func.coalesce(Mention.published_at, Mention.collected_at)
    topic = func.coalesce(Mention.topic, "Other").label("topic")
    current_count = func.sum(case((event_time >= current_start, 1), else_=0)).label("current_count")
    previous_count = func.sum(case((event_time < current_start, 1), else_=0)).label("previous_count")
    rows = session.execute(
        select(topic, current_count, previous_count)
        .where(
            func.lower(Mention.keyword) == keyword.casefold(),
            event_time >= previous_start,
            event_time <= end,
        )
        .group_by(topic)
        .order_by(current_count.desc(), topic.asc())
    ).all()
    results: list[dict[str, int | float | str | bool | None]] = []
    for topic_name, current, previous in rows:
        current_value = int(current or 0)
        previous_value = int(previous or 0)
        if current_value == 0:
            continue
        percent_change = (
            round((current_value - previous_value) / previous_value * 100, 1)
            if previous_value
            else None
        )
        results.append(
            {
                "topic": str(topic_name),
                "current_count": current_value,
                "previous_count": previous_value,
                "change_percent": percent_change,
                "new_topic": previous_value == 0,
                "increased": current_value > previous_value,
            }
        )
    return results


def get_negative_sentiment_spike(
    session: Session,
    *,
    keyword: str,
    window_days: int = 7,
    minimum_negative_mentions: int = 3,
    minimum_rate_increase: float = 0.15,
    now: datetime | None = None,
) -> dict[str, int | float | bool]:
    if window_days < 1 or minimum_negative_mentions < 1:
        raise ValueError("window_days and minimum_negative_mentions must be positive")
    end = now or datetime.now(UTC)
    current_start = end - timedelta(days=window_days)
    previous_start = current_start - timedelta(days=window_days)
    event_time = func.coalesce(Mention.published_at, Mention.collected_at)
    current_period = event_time >= current_start
    current_total_expr = func.sum(case((current_period, 1), else_=0))
    current_negative_expr = func.sum(
        case((current_period & (Mention.sentiment == "Negative"), 1), else_=0)
    )
    previous_total_expr = func.sum(case((~current_period, 1), else_=0))
    previous_negative_expr = func.sum(
        case((~current_period & (Mention.sentiment == "Negative"), 1), else_=0)
    )
    row = session.execute(
        select(
            current_total_expr,
            current_negative_expr,
            previous_total_expr,
            previous_negative_expr,
        ).where(
            func.lower(Mention.keyword) == keyword.casefold(),
            event_time >= previous_start,
            event_time <= end,
        )
    ).one()
    current_total, current_negative, previous_total, previous_negative = (
        int(value or 0) for value in row
    )
    current_rate = current_negative / current_total if current_total else 0.0
    previous_rate = previous_negative / previous_total if previous_total else 0.0
    rate_increase = current_rate - previous_rate
    baseline_available = previous_total > 0
    detected = baseline_available and current_negative >= minimum_negative_mentions and (
        rate_increase >= minimum_rate_increase
        or current_negative >= max(minimum_negative_mentions, previous_negative * 2)
    )
    return {
        "detected": detected,
        "window_days": window_days,
        "current_total": current_total,
        "current_negative": current_negative,
        "current_negative_rate": round(current_rate, 4),
        "previous_total": previous_total,
        "previous_negative": previous_negative,
        "previous_negative_rate": round(previous_rate, 4),
        "rate_change_percentage_points": round(rate_increase * 100, 1),
        "baseline_available": baseline_available,
    }


def get_competitor_comparison(
    session: Session,
    *,
    brands: tuple[str, ...] = ("Toyota", "Hyundai", "Kia"),
    days: int = 30,
    now: datetime | None = None,
) -> list[dict[str, object]]:
    if days < 1:
        raise ValueError("days must be positive")
    end = now or datetime.now(UTC)
    since = end - timedelta(days=days)
    event_time = func.coalesce(Mention.published_at, Mention.collected_at)
    brand_key = func.lower(Mention.keyword).label("brand")
    sentiment = func.coalesce(Mention.sentiment, "Unclassified").label("sentiment")
    topic = func.coalesce(Mention.topic, "Other").label("topic")
    rows = session.execute(
        select(brand_key, sentiment, topic, func.count())
        .where(
            func.lower(Mention.keyword).in_([brand.casefold() for brand in brands]),
            event_time >= since,
            event_time <= end,
        )
        .group_by(brand_key, sentiment, topic)
    ).all()
    aggregates: dict[str, dict[str, object]] = {
        brand.casefold(): {
            "brand": brand,
            "mention_volume": 0,
            "sentiment_distribution": {},
            "topics": {},
            "common_complaints": [],
        }
        for brand in brands
    }
    for brand, sentiment_name, topic_name, count in rows:
        record = aggregates[brand]
        record["mention_volume"] += int(count)
        sentiment_counts = record["sentiment_distribution"]
        topic_counts = record["topics"]
        sentiment_counts[sentiment_name] = int(count) + sentiment_counts.get(sentiment_name, 0)
        topic_counts[topic_name] = int(count) + topic_counts.get(topic_name, 0)

    complaint_text = func.coalesce(Mention.content, Mention.title, Mention.normalized_text)
    complaints = session.execute(
        select(brand_key, complaint_text, func.count())
        .where(
            func.lower(Mention.keyword).in_([brand.casefold() for brand in brands]),
            Mention.topic == "Complaints",
            event_time >= since,
            event_time <= end,
            complaint_text.is_not(None),
        )
        .group_by(brand_key, complaint_text)
        .order_by(func.count().desc())
    ).all()
    complaint_counts: dict[str, dict[str, int]] = {}
    for brand, text, count in complaints:
        snippets = complaint_counts.setdefault(brand, {})
        snippets[text] = snippets.get(text, 0) + int(count)
    for brand, record in aggregates.items():
        record["topics"] = [
            {"topic": name, "count": count}
            for name, count in sorted(record["topics"].items(), key=lambda item: (-item[1], item[0]))
        ]
        record["common_complaints"] = [
            {"text": text[:280], "count": count}
            for text, count in sorted(complaint_counts.get(brand, {}).items(), key=lambda item: (-item[1], item[0]))[:5]
        ]
    return list(aggregates.values())


def _mention_conditions(
    *,
    source: str | None = None,
    keyword: str | None = None,
    sentiment: str | None = None,
    topic: str | None = None,
    published_after: datetime | None = None,
    published_before: datetime | None = None,
    search: str | None = None,
):
    conditions = []
    if source is not None:
        conditions.append(Mention.source == source)
    if keyword is not None:
        conditions.append(Mention.keyword == keyword)
    if sentiment is not None:
        conditions.append(Mention.sentiment == sentiment)
    if topic is not None:
        conditions.append(Mention.topic == topic)
    if published_after is not None:
        conditions.append(Mention.published_at >= published_after)
    if published_before is not None:
        conditions.append(Mention.published_at <= published_before)
    if search:
        escaped = search.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        conditions.append(
            or_(
                Mention.title.ilike(pattern, escape="\\"),
                Mention.content.ilike(pattern, escape="\\"),
                Mention.normalized_text.ilike(pattern, escape="\\"),
            )
        )
    return conditions