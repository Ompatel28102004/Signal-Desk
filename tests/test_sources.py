from datetime import UTC, datetime

import httpx
import pytest

from backend.app.config import Settings
from backend.app.ingestion.base import BaseSource
from backend.app.ingestion.manager import IngestionManager
from backend.app.ingestion.models import RawMention
from backend.app.ingestion.sources import build_ingestion_manager
from backend.app.ingestion.sources.hacker_news import HackerNewsSource
from backend.app.ingestion.sources.rss import RSSFeedSource


def test_hacker_news_maps_and_deduplicates_hits() -> None:
    payload = {
        "hits": [
            {
                "objectID": "42",
                "story_title": "A <b>Launch</b>",
                "comment_text": "Text &amp; details",
                "author": "ada",
                "url": "https://example.test/story",
                "created_at": "2025-02-01T10:00:00Z",
            },
            {"objectID": "42", "story_title": "duplicate"},
        ]
    }
    client = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    )

    mentions = HackerNewsSource(client=client).search("launch", limit=2)

    assert len(mentions) == 1
    assert mentions[0].external_id == "42"
    assert mentions[0].title == "A Launch"
    assert mentions[0].content == "Text & details"
    assert mentions[0].author == "ada"
    assert mentions[0].published_at == datetime(2025, 2, 1, 10, tzinfo=UTC)


def test_hacker_news_retries_transient_status_with_backoff() -> None:
    calls = 0
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(503, request=request)
        return httpx.Response(200, json={"hits": []}, request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    source = HackerNewsSource(
        client=client,
        max_retries=1,
        backoff_seconds=0.1,
        sleep=sleeps.append,
    )

    assert source.search("launch", limit=1) == []
    assert calls == 2
    assert sleeps == [0.1]


def test_hacker_news_retries_timeout_with_backoff() -> None:
    calls = 0
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ReadTimeout("temporary timeout", request=request)
        return httpx.Response(200, json={"hits": []}, request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    source = HackerNewsSource(
        client=client,
        max_retries=1,
        backoff_seconds=0.1,
        sleep=sleeps.append,
    )

    assert source.search("launch", limit=1) == []
    assert calls == 2
    assert sleeps == [0.1]


def test_hacker_news_rejects_malformed_json() -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=b"not json", request=request)
        )
    )

    with pytest.raises(ValueError, match="invalid JSON"):
        HackerNewsSource(client=client, max_retries=0).search("launch", limit=1)


def test_rss_filters_keyword_and_deduplicates_entries() -> None:
    feed = b"""<?xml version="1.0"?>
    <rss version="2.0"><channel><title>Test feed</title>
    <item><guid>item-1</guid><title>New product launch</title>
    <description><![CDATA[<p>Useful <b>details</b></p>]]></description>
    <link>https://example.test/one</link><author>ada</author>
    <pubDate>Sat, 01 Feb 2025 10:00:00 +0000</pubDate></item>
    <item><guid>item-1</guid><title>Duplicate launch</title></item>
    <item><guid>item-2</guid><title>Unrelated item</title></item>
    </channel></rss>"""
    client = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=feed))
    )

    mentions = RSSFeedSource("https://example.test/feed.xml", client=client).search(
        "product launch", limit=10
    )

    assert len(mentions) == 1
    assert mentions[0].external_id == "item-1"
    assert mentions[0].title == "New product launch"
    assert mentions[0].content == "Useful details"
    assert mentions[0].author == "ada"
    assert mentions[0].url == "https://example.test/one"
    assert mentions[0].published_at == datetime(2025, 2, 1, 10, tzinfo=UTC)


def test_rss_timeout_does_not_discard_other_source_results() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout", request=request)

    client = httpx.Client(transport=httpx.MockTransport(timeout))
    rss = RSSFeedSource("https://example.test/feed.xml", client=client, max_retries=0)

    class WorkingSource(BaseSource):
        @property
        def source_name(self) -> str:
            return "working"

        def search(self, keyword: str, limit: int) -> list[RawMention]:
            return [RawMention(external_id="ok", content="launch")]

    result = IngestionManager([rss, WorkingSource()]).search("launch", limit=1)

    assert [mention.source for mention in result.mentions] == ["working"]
    assert len(result.failures) == 1
    assert result.failures[0].source.startswith("rss:")


def test_configured_manager_registers_every_rss_feed() -> None:
    config = Settings(
        _env_file=None,
        rss_feed_urls=[
            "https://one.example/feed.xml",
            "https://two.example/rss.xml",
        ],
    )

    manager = build_ingestion_manager(config)

    assert len(manager._sources) == 4
    assert manager._sources[0].source_name == "hacker_news"
    assert all(isinstance(source, RSSFeedSource) for source in manager._sources[1:3])
    assert manager._sources[3].source_name == "youtube"
    assert manager._sources[3].enabled is False
