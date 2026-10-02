import pytest

from backend.app.config import settings
from backend.app.ingestion.sources.youtube import YouTubeDataSource


HAS_YOUTUBE_API_KEY = bool(
    settings.youtube_api_key and settings.youtube_api_key.get_secret_value()
)


@pytest.mark.integration
@pytest.mark.skipif(not HAS_YOUTUBE_API_KEY, reason="Set YOUTUBE_API_KEY for the live API-health check")
def test_youtube_api_health() -> None:
    source = YouTubeDataSource(
        settings.youtube_api_key,
        timeout_seconds=5,
        max_retries=0,
    )

    assert source.health_check() is True