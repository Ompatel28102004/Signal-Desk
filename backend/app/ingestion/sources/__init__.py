from backend.app.config import Settings, settings
from backend.app.ingestion.manager import IngestionManager
from backend.app.ingestion.sources.hacker_news import HackerNewsSource
from backend.app.ingestion.sources.rss import RSSFeedSource
from backend.app.ingestion.sources.youtube import YouTubeDataSource


def build_ingestion_manager(
    config: Settings = settings,
    *,
    source_names: set[str] | None = None,
) -> IngestionManager:
    source_options = {
        "timeout_seconds": config.ingestion_request_timeout_seconds,
        "max_retries": config.ingestion_max_retries,
        "backoff_seconds": config.ingestion_retry_backoff_seconds,
    }
    sources = [HackerNewsSource(**source_options)]
    sources.extend(RSSFeedSource(feed_url, **source_options) for feed_url in config.rss_feed_urls)
    sources.append(
        YouTubeDataSource(
            api_key=config.youtube_api_key,
            max_videos_per_search=config.youtube_max_videos,
            comments_per_video=config.youtube_comments_per_video,
            max_comment_pages_per_video=config.youtube_max_comment_pages_per_video,
            **source_options,
        )
    )
    if source_names is None:
        return IngestionManager(sources)

    valid_names = {"hacker_news", "rss", "youtube"}
    unknown_names = source_names - valid_names
    if unknown_names:
        raise ValueError(f"Unknown source names: {', '.join(sorted(unknown_names))}")
    selected = [
        source
        for source in sources
        if source.source_name in source_names
        or ("rss" in source_names and source.source_name.startswith("rss:"))
    ]
    if "rss" in source_names and not config.rss_feed_urls:
        raise ValueError("RSS source is not configured")
    return IngestionManager(selected)


__all__ = [
    "HackerNewsSource",
    "RSSFeedSource",
    "YouTubeDataSource",
    "build_ingestion_manager",
]