import logging
from collections.abc import Sequence

from apscheduler.schedulers.blocking import BlockingScheduler
from sqlalchemy.orm import Session

from backend.app.api.service import collect_and_persist
from backend.app.config import settings
from backend.app.db.session import engine
from backend.app.ingestion.sources import build_ingestion_manager


logger = logging.getLogger(__name__)


def run_collection_cycle(
    keywords: Sequence[str] | None = None,
    source_names: set[str] | None = None,
) -> None:
    if engine is None:
        logger.error("scheduler.database_not_configured")
        return
    configured_keywords = [
        keyword.strip()
        for keyword in (keywords if keywords is not None else settings.scheduled_ingestion_keywords)
        if keyword.strip()
    ]
    if not configured_keywords:
        logger.warning("scheduler.no_keywords_configured")
        return

    selected_sources = set(source_names or settings.scheduled_ingestion_sources)
    if "rss" in selected_sources and not settings.rss_feed_urls:
        selected_sources.remove("rss")
    manager = build_ingestion_manager(settings, source_names=selected_sources)

    for keyword in configured_keywords:
        try:
            with Session(engine) as session:
                result = collect_and_persist(
                    session,
                    manager,
                    keyword=keyword,
                    limit=settings.scheduled_ingestion_limit,
                )
            logger.info(
                "scheduler.collection.completed",
                extra={
                    "keyword": keyword,
                    "collected_count": len(result.ingestion.mentions),
                    "inserted_count": result.inserted,
                    "failure_count": len(result.ingestion.failures),
                    "disabled_source_count": len(result.ingestion.disabled_sources),
                },
            )
        except Exception as error:
            logger.error(
                "scheduler.collection.failed",
                extra={"keyword": keyword, "error_type": type(error).__name__},
            )


def main() -> None:
    if not settings.scheduled_ingestion_enabled:
        logger.info("scheduler.disabled", extra={"setting": "SCHEDULED_INGESTION_ENABLED"})
        return
    if engine is None:
        raise SystemExit("Scheduled ingestion requires DATABASE_URL")
    if not any(keyword.strip() for keyword in settings.scheduled_ingestion_keywords):
        raise SystemExit("Scheduled ingestion requires SCHEDULED_INGESTION_KEYWORDS")

    scheduler = BlockingScheduler(timezone="UTC")
    scheduler.add_job(
        run_collection_cycle,
        trigger="interval",
        minutes=settings.scheduled_ingestion_interval_minutes,
        id="scheduled-mention-collection",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=300,
    )
    logger.info(
        "scheduler.started",
        extra={
            "interval_minutes": settings.scheduled_ingestion_interval_minutes,
            "keyword_count": len(settings.scheduled_ingestion_keywords),
            "sources": settings.scheduled_ingestion_sources,
        },
    )
    run_collection_cycle()
    scheduler.start()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()