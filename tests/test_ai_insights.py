import json
from collections.abc import Sequence

import httpx
import pytest
from pydantic import SecretStr

from backend.app.ai.models import InsightContext, InsightContent
from backend.app.ai.providers import AIProvider, GeminiProvider, OllamaProvider
from backend.app.ai.service import AIInsightsService, _default_providers, build_insight_context
from backend.app.config import Settings
from backend.app.ingestion.models import NormalizedMention


def _content(overall: str = "Discussion summary.") -> InsightContent:
    return InsightContent(
        overall_discussion=overall,
        common_themes=["Product"],
        positive_themes=["Ease of use"],
        negative_themes=["Slow support"],
        common_complaints=["Support delays"],
        frequently_discussed_features=["Feature updates"],
        opportunities=["Improve response times"],
    )


def _mention(
    index: int,
    *,
    sentiment: str = "Neutral",
    topic: str = "Product",
    title: str = "Product discussion",
    content: str = "A representative product comment.",
) -> NormalizedMention:
    return NormalizedMention(
        source="unit-test",
        external_id=f"id-{index}",
        keyword="product",
        title=title,
        content=content,
        normalized_text=f"{title}\n{content}",
        sentiment=sentiment,
        sentiment_score=0.9,
        topic=topic,
        topic_score=0.8,
    )


class FakeProvider(AIProvider):
    def __init__(
        self,
        name: str,
        *,
        available: bool,
        result: object | None = None,
        failure: Exception | None = None,
    ) -> None:
        self.name = name
        self.available = available
        self.result = result or _content(f"{name} summary.")
        self.failure = failure
        self.availability_checks = 0
        self.calls: list[InsightContext] = []

    def is_available(self) -> bool:
        self.availability_checks += 1
        return self.available

    def summarize(self, context: InsightContext) -> InsightContent:
        self.calls.append(context)
        if self.failure:
            raise self.failure
        return self.result


def test_context_contains_aggregates_and_at_most_six_representative_snippets() -> None:
    mentions = [
        _mention(
            index,
            sentiment="Positive" if index < 10 else "Negative" if index < 20 else "Neutral",
            topic="Features" if index % 2 else "Complaints",
            title=f"Title {index}",
            content=f"Snippet body {index} " + ("x" * 400),
        )
        for index in range(30)
    ]

    context = build_insight_context("product", mentions)
    serialized = context.model_dump_json()

    assert context.total_mentions == 30
    assert context.sentiment_distribution == {"Positive": 10, "Negative": 10, "Neutral": 10}
    assert len(context.topic_distribution) == 2
    assert len(context.representative_positive) == 3
    assert len(context.representative_negative) == 3
    assert all(len(item.text) <= 280 for item in context.representative_positive)
    assert all(f"id-{index}" not in serialized for index in range(30))
    assert "x" * 300 not in serialized


def test_empty_context_uses_deterministic_fallback_without_providers() -> None:
    provider = FakeProvider("ollama", available=True)

    result = AIInsightsService([provider]).summarize("product", [])

    assert result.provider == "deterministic"
    assert result.overall_discussion == "No mentions were available to summarize."
    assert provider.availability_checks == 0
    assert provider.calls == []


def test_ollama_has_priority_over_gemini() -> None:
    ollama = FakeProvider("ollama", available=True)
    gemini = FakeProvider("gemini", available=True)

    result = AIInsightsService([ollama, gemini]).summarize(
        "product", [_mention(1, sentiment="Positive")]
    )

    assert result.provider == "ollama"
    assert ollama.availability_checks == 1
    assert gemini.availability_checks == 0
    assert len(ollama.calls) == 1


def test_ollama_uses_separate_longer_timeout_than_gemini() -> None:
    providers = _default_providers(
        Settings(
            ai_request_timeout_seconds=12,
            ollama_request_timeout_seconds=60,
        )
    )

    assert providers[0].timeout_seconds == 60
    assert providers[0].readiness_timeout_seconds == 5
    assert providers[1].timeout_seconds == 12


def test_service_falls_through_provider_failure_then_uses_gemini() -> None:
    ollama = FakeProvider("ollama", available=True, failure=RuntimeError("offline model"))
    gemini = FakeProvider("gemini", available=True)

    result = AIInsightsService([ollama, gemini]).summarize(
        "product", [_mention(1, sentiment="Negative", topic="Complaints")]
    )

    assert result.provider == "gemini"
    assert len(ollama.calls) == 1
    assert len(gemini.calls) == 1


@pytest.mark.parametrize("status_code", [429, 503])
def test_gemini_transient_http_errors_fall_back_without_failing_summary(status_code: int) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json={"error": {"status": "UNAVAILABLE"}}, request=request)

    ollama = FakeProvider("ollama", available=False)
    gemini = GeminiProvider(
        SecretStr("test-gemini-key"),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    result = AIInsightsService([ollama, gemini]).summarize("product", [_mention(1)])

    assert result.provider == "deterministic"
    assert result.overall_discussion.startswith("1 mentions about product")


def test_invalid_provider_json_is_rejected_and_falls_back() -> None:
    provider = FakeProvider("gemini", available=True, result={"overall_discussion": "incomplete"})

    result = AIInsightsService([provider]).summarize("product", [_mention(1)])

    assert result.provider == "deterministic"
    assert result.overall_discussion.startswith("1 mentions about product")


def test_deterministic_fallback_uses_topic_and_sentiment_aggregates() -> None:
    mentions = [
        _mention(1, sentiment="Positive", topic="Features"),
        _mention(2, sentiment="Negative", topic="Complaints"),
    ]

    result = AIInsightsService([]).summarize("release", mentions)

    assert result.provider == "deterministic"
    assert "Features" in " ".join(result.positive_themes)
    assert result.common_complaints == ["Complaints appeared in 1 mentions."]
    assert "Complaints" in " ".join(result.opportunities)
    assert result.model_validate_json(result.model_dump_json()) == result


def test_ollama_detection_requires_configured_model() -> None:
    responses = [
        httpx.Response(200, json={"models": [{"name": "other:latest"}]}),
        httpx.Response(200, json={"models": [{"name": "llama3.2:3b"}]}),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return responses.pop(0)

    provider = OllamaProvider(client=httpx.Client(transport=httpx.MockTransport(handler)))

    assert provider.is_available() is False
    assert provider.is_available() is True


def test_ollama_sends_aggregate_as_json_schema_request() -> None:
    captured: list[dict] = []
    expected = _content().model_dump_json()

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={"response": expected}, request=request)

    provider = OllamaProvider(client=httpx.Client(transport=httpx.MockTransport(handler)))
    context = build_insight_context("product", [_mention(1)])

    result = provider.summarize(context)

    assert result.overall_discussion == "Discussion summary."
    assert captured[0]["stream"] is False
    assert captured[0]["format"]["type"] == "object"
    assert "id-1" not in captured[0]["prompt"]


def test_gemini_is_unavailable_without_key() -> None:
    provider = GeminiProvider(None)
    assert provider.is_available() is False


def test_gemini_uses_pinned_model_bounded_context_and_api_key_header() -> None:
    captured: list[httpx.Request] = []
    expected = _content("Gemini summary.").model_dump_json()

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": expected}]}}]},
            request=request,
        )

    key = SecretStr("test-gemini-key")
    provider = GeminiProvider(key, client=httpx.Client(transport=httpx.MockTransport(handler)))
    context = build_insight_context("product", [_mention(1)])

    result = provider.summarize(context)

    request = captured[0]
    payload = json.loads(request.content)
    assert request.url.path.endswith("/models/gemini-3.8-flash:generateContent")
    assert request.url.params == httpx.QueryParams()
    assert request.headers["x-goog-api-key"] == key.get_secret_value()
    assert "tools" not in payload
    assert payload["generationConfig"]["maxOutputTokens"] == 512
    assert payload["generationConfig"]["responseFormat"]["text"]["schema"]["type"] == "object"
    assert "id-1" not in request.content.decode()
    assert result.overall_discussion == "Gemini summary."
