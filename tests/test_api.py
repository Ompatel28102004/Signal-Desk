from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.app.ai.models import AIInsights
from backend.app.ai.service import deterministic_summary
from backend.app.api import routes
from backend.app.api.dependencies import (
    get_ai_insights_service,
    get_database_session,
    get_ingestion_manager,
)
from backend.app.ai.models import InsightContext
from backend.app.ingestion.models import IngestionResult, NormalizedMention, RawMention
from backend.app.main import app


@pytest.fixture
def client():
    app.dependency_overrides.clear()
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _mention(**overrides) -> NormalizedMention:
    values = {
        "source": "hacker_news",
        "external_id": "story-1",
        "keyword": "spring launch",
        "title": "Spring product launch",
        "content": "A helpful product update.",
        "published_at": datetime(2025, 1, 1, tzinfo=UTC),
        "normalized_text": "spring product launch\na helpful product update",
        "content_hash": "a" * 64,
        "relevance_score": 1.0,
        "relevance_reason": "keyword_phrase_in_title",
        "sentiment": "Positive",
        "sentiment_score": 1.0,
        "topic": "Product",
        "topic_score": 1.0,
    }
    values.update(overrides)
    return NormalizedMention(**values)


class SearchManager:
    def __init__(self, mentions: list[NormalizedMention] | None = None) -> None:
        self.mentions = mentions or [_mention()]
        self.search_args = None

    def search(self, keyword: str, limit: int, **options) -> IngestionResult:
        self.search_args = (keyword, limit, options)
        return IngestionResult(mentions=self.mentions)


def test_health_contract_and_no_secret_values(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["application"]["status"] == "running"
    assert "DATABASE_URL" not in response.text
    assert "GEMINI_API_KEY" not in response.text


def test_search_validates_keyword_and_respects_source_options(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = SearchManager()
    calls = []

    def build_manager(config, *, source_names=None):
        calls.append(source_names)
        return manager

    monkeypatch.setattr(routes, "build_ingestion_manager", build_manager)

    invalid = client.post("/api/search", json={"keyword": "  "})
    response = client.post(
        "/api/search",
        json={"keyword": " spring launch ", "sources": ["hacker_news"], "limit": 7},
    )

    assert invalid.status_code == 422
    assert response.status_code == 200
    assert calls == [{"hacker_news"}]
    assert manager.search_args == ("spring launch", 7, {})
    assert response.json()["mentions"][0]["topic"] == "Product"


def test_search_returns_422_for_unknown_source(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def build_manager(config, *, source_names=None):
        raise ValueError("Unknown source names: unknown")

    monkeypatch.setattr(routes, "build_ingestion_manager", build_manager)

    response = client.post(
        "/api/search",
        json={"keyword": "spring launch", "sources": ["hacker_news"]},
    )

    assert response.status_code == 422


def test_mentions_endpoint_passes_filters_and_returns_pagination(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_session = object()
    app.dependency_overrides[get_database_session] = lambda: fake_session
    mention = _mention()
    captured = {}

    def list_page(session, **filters):
        captured["session"] = session
        captured.update(filters)
        return [mention], 21

    monkeypatch.setattr(routes.mention_repository, "list_mentions_page", list_page)

    response = client.get(
        "/api/mentions?keyword=spring%20launch&search=launch&sentiment=Positive&page=2&page_size=10"
    )

    assert response.status_code == 200
    assert captured["session"] is fake_session
    assert captured["offset"] == 10
    assert captured["limit"] == 10
    assert captured["search"] == "launch"
    assert response.json()["pagination"] == {
        "page": 2,
        "page_size": 10,
        "total": 21,
        "pages": 3,
    }


def test_get_mention_returns_404_for_missing_record(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app.dependency_overrides[get_database_session] = lambda: object()
    monkeypatch.setattr(routes.mention_repository, "get_by_id", lambda session, mention_id: None)

    response = client.get(f"/api/mentions/{uuid4()}")

    assert response.status_code == 404


def test_analytics_returns_typed_aggregates(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app.dependency_overrides[get_database_session] = lambda: object()
    monkeypatch.setattr(
        routes,
        "analytics_response_data",
        lambda session, *, keyword, days: {
            "keyword": keyword,
            "days": days,
            "total": 4,
            "sentiment_distribution": {"Positive": 3, "Negative": 1},
            "topics": [{"name": "Product", "count": 4}],
            "time_series": [{"bucket": datetime(2025, 1, 1, tzinfo=UTC), "count": 4}],
        },
    )

    response = client.get("/api/analytics?keyword=spring%20launch&days=14")

    assert response.status_code == 200
    assert response.json()["total"] == 4
    assert response.json()["topics"][0] == {"name": "Product", "count": 4}
    assert len(response.json()["time_series"]) == 1


def test_insights_endpoint_returns_validated_summary(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app.dependency_overrides[get_database_session] = lambda: object()
    summary = AIInsights(
        **deterministic_summary(InsightContext(
            keyword="spring launch",
            total_mentions=0,
            sentiment_distribution={},
            topic_distribution=[],
            topic_sentiment_distribution=[],
            common_themes=[],
            representative_positive=[],
            representative_negative=[],
        )).model_dump(),
        provider="deterministic",
    )
    monkeypatch.setattr(routes, "summarize_stored_mentions", lambda *args, **kwargs: (summary, [object()]))

    response = client.get("/api/insights?keyword=spring%20launch")

    assert response.status_code == 200
    assert response.json()["mentions_analyzed"] == 1
    assert response.json()["insights"]["provider"] == "deterministic"


def test_sources_reports_optional_sources_without_credentials(client: TestClient) -> None:
    response = client.get("/api/sources")

    assert response.status_code == 200
    payload = response.json()["sources"]
    names = {item["name"] for item in payload}
    assert names == {"hacker_news", "rss", "youtube"}
    assert "GEMINI_API_KEY" not in response.text


def test_collect_persists_then_classifies_then_summarizes(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class FakeSession:
        def commit(self) -> None:
            events.append("commit")

    class FakeManager(SearchManager):
        def search(self, keyword: str, limit: int, **options) -> IngestionResult:
            assert options == {"classify": False}
            events.append("ingestion")
            return IngestionResult(mentions=[_mention(sentiment=None, topic=None)])

        def classify_many(self, mentions: list[NormalizedMention]) -> list[NormalizedMention]:
            assert events[-1] == "commit"
            events.append("nlp")
            return [item.model_copy(update={"sentiment": "Positive", "topic": "Product"}) for item in mentions]

    class FakeInsights:
        def summarize(self, keyword: str, mentions: list[NormalizedMention]) -> AIInsights:
            assert events[-1] == "commit"
            events.append("insights")
            content = deterministic_summary(InsightContext(
                keyword=keyword,
                total_mentions=len(mentions),
                sentiment_distribution={"Positive": len(mentions)},
                topic_distribution=[],
                topic_sentiment_distribution=[],
                common_themes=[],
                representative_positive=[],
                representative_negative=[],
            ))
            return AIInsights(**content.model_dump(), provider="deterministic")

    row = SimpleNamespace(
        id=uuid4(),
        source="hacker_news",
        external_id="story-1",
        keyword="spring launch",
        title="Spring product launch",
        content="A helpful product update.",
        author=None,
        url=None,
        published_at=datetime(2025, 1, 1, tzinfo=UTC),
        collected_at=datetime(2025, 1, 1, tzinfo=UTC),
        engagement=None,
        normalized_text="spring product launch",
        content_hash="a" * 64,
        relevance_score=1.0,
        relevance_reason="keyword_phrase_in_title",
        sentiment=None,
        sentiment_score=None,
        topic=None,
        topic_score=None,
        created_at=datetime(2025, 1, 1, tzinfo=UTC),
        updated_at=datetime(2025, 1, 1, tzinfo=UTC),
    )

    def add_or_get(session, payload):
        assert events == ["ingestion"]
        assert payload.sentiment is None
        events.append("persist")
        return row, True

    monkeypatch.setattr(routes.mention_repository, "add_or_get", add_or_get)
    app.dependency_overrides[get_database_session] = lambda: FakeSession()
    app.dependency_overrides[get_ingestion_manager] = lambda: FakeManager()
    app.dependency_overrides[get_ai_insights_service] = lambda: FakeInsights()

    response = client.post("/api/collect", json={"keyword": "spring launch", "limit": 5})

    assert response.status_code == 200
    assert events == ["ingestion", "persist", "commit", "nlp", "commit", "insights"]
    assert response.json()["inserted"] == 1
    assert response.json()["classified"] == 1
    assert response.json()["insights"]["provider"] == "deterministic"