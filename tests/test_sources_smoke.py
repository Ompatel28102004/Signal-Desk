import os

import pytest

from backend.app.ingestion.sources.hacker_news import HackerNewsSource


@pytest.mark.integration
@pytest.mark.skipif(
    os.getenv("RUN_SOURCE_SMOKE_TESTS") != "1",
    reason="Set RUN_SOURCE_SMOKE_TESTS=1 to make one live Hacker News request",
)
def test_hacker_news_live_smoke() -> None:
    mentions = HackerNewsSource(timeout_seconds=5, max_retries=0).search("open source", limit=1)

    assert len(mentions) <= 1
    for mention in mentions:
        assert mention.external_id
        assert mention.title or mention.content