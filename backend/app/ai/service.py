import logging
from collections import Counter
from collections.abc import Iterable, Sequence

from backend.app.ai.models import (
    AIInsights,
    InsightContext,
    InsightContent,
    RepresentativeMention,
    TopicCount,
    TopicSentimentCount,
)
from backend.app.ai.providers import AIProvider, GeminiProvider, OllamaProvider
from backend.app.config import Settings, settings
from backend.app.ingestion.models import NormalizedMention


logger = logging.getLogger(__name__)
POSITIVE_SAMPLE_LIMIT = 3
NEGATIVE_SAMPLE_LIMIT = 3
SAMPLE_TEXT_LIMIT = 280


class AIInsightsService:
    def __init__(
        self,
        providers: Sequence[AIProvider] | None = None,
    ) -> None:
        self._providers = tuple(providers) if providers is not None else _default_providers(settings)

    def summarize(self, keyword: str, mentions: Iterable[NormalizedMention]) -> AIInsights:
        context = build_insight_context(keyword, mentions)
        if context.total_mentions == 0:
            fallback = deterministic_summary(context)
            return AIInsights(provider="deterministic", **fallback.model_dump())
        for provider in self._providers:
            try:
                if not provider.is_available():
                    continue
                content = provider.summarize(context)
                validated = InsightContent.model_validate(content)
                return AIInsights(provider=provider.name, **validated.model_dump())
            except Exception as error:
                logger.warning(
                    "ai.provider.failed",
                    extra={"provider": provider.name, "error_type": type(error).__name__},
                )

        fallback = deterministic_summary(context)
        return AIInsights(provider="deterministic", **fallback.model_dump())


def build_insight_context(
    keyword: str,
    mentions: Iterable[NormalizedMention],
) -> InsightContext:
    mention_list = list(mentions)
    sentiment_counts: Counter[str] = Counter()
    topic_counts: Counter[str] = Counter()
    topic_sentiment_counts: Counter[tuple[str, str]] = Counter()
    for mention in mention_list:
        sentiment = mention.sentiment or "Unclassified"
        topic = mention.topic or "Other"
        sentiment_counts[sentiment] += 1
        topic_counts[topic] += 1
        topic_sentiment_counts[(topic, sentiment)] += 1

    topic_distribution = [
        TopicCount(topic=topic, count=count)
        for topic, count in topic_counts.most_common(8)
    ]
    topic_sentiment_distribution = [
        TopicSentimentCount(topic=topic, sentiment=sentiment, count=count)
        for (topic, sentiment), count in topic_sentiment_counts.most_common(24)
    ]
    positive = _representatives(mention_list, "Positive", POSITIVE_SAMPLE_LIMIT)
    negative = _representatives(mention_list, "Negative", NEGATIVE_SAMPLE_LIMIT)
    return InsightContext(
        keyword=keyword[:255],
        total_mentions=len(mention_list),
        sentiment_distribution=dict(sentiment_counts),
        topic_distribution=topic_distribution,
        topic_sentiment_distribution=topic_sentiment_distribution,
        common_themes=[item.topic for item in topic_distribution[:5]],
        representative_positive=positive,
        representative_negative=negative,
    )


def deterministic_summary(context: InsightContext) -> InsightContent:
    if context.total_mentions == 0:
        return InsightContent(
            overall_discussion="No mentions were available to summarize.",
            common_themes=[],
            positive_themes=[],
            negative_themes=[],
            common_complaints=[],
            frequently_discussed_features=[],
            opportunities=[],
        )

    leading_topic = context.topic_distribution[0].topic if context.topic_distribution else "Other"
    sentiment_text = ", ".join(
        f"{sentiment.lower()}: {count}"
        for sentiment, count in sorted(context.sentiment_distribution.items())
        if count
    )
    overall = (
        f"{context.total_mentions} mentions about {context.keyword} focused mainly on "
        f"{leading_topic}; sentiment counts were {sentiment_text or 'unclassified'}."
    )

    positive_topics = _top_topics_for_sentiment(context, "Positive")
    negative_topics = _top_topics_for_sentiment(context, "Negative")
    topic_counts = {item.topic: item.count for item in context.topic_distribution}
    complaint_count = topic_counts.get("Complaints", 0)
    feature_count = topic_counts.get("Features", 0)
    complaints = (
        [f"Complaints appeared in {complaint_count} mentions."] if complaint_count else []
    )
    features = (
        [f"Features were discussed in {feature_count} mentions."] if feature_count else []
    )
    opportunities = [
        f"Review negative feedback about {topic}." for topic in negative_topics[:3]
    ]
    return InsightContent(
        overall_discussion=overall,
        common_themes=[f"{item.topic}: {item.count}" for item in context.topic_distribution[:4]],
        positive_themes=positive_topics,
        negative_themes=negative_topics,
        common_complaints=complaints,
        frequently_discussed_features=features,
        opportunities=opportunities,
    )


def _top_topics_for_sentiment(context: InsightContext, sentiment: str) -> list[str]:
    items = [
        item for item in context.topic_sentiment_distribution if item.sentiment == sentiment
    ]
    items.sort(key=lambda item: item.count, reverse=True)
    return [f"{item.topic}: {item.count}" for item in items[:3]]


def _representatives(
    mentions: Sequence[NormalizedMention],
    sentiment: str,
    limit: int,
) -> list[RepresentativeMention]:
    selected = [mention for mention in mentions if mention.sentiment == sentiment]
    selected.sort(
        key=lambda mention: (
            mention.sentiment_score or 0,
            mention.relevance_score or 0,
            mention.collected_at,
        ),
        reverse=True,
    )
    result: list[RepresentativeMention] = []
    for mention in selected[:limit]:
        title = (mention.title or "").strip()[:160] or None
        text = " ".join(
            part.strip() for part in (mention.title, mention.content) if part and part.strip()
        )[:SAMPLE_TEXT_LIMIT]
        if text:
            result.append(RepresentativeMention(title=title, text=text))
    return result


def _default_providers(config: Settings) -> tuple[AIProvider, ...]:
    return (
        OllamaProvider(
            base_url=config.ollama_base_url,
            model=config.ollama_model,
            timeout_seconds=config.ollama_request_timeout_seconds,
        ),
        GeminiProvider(
            api_key=config.gemini_api_key,
            timeout_seconds=config.ai_request_timeout_seconds,
        ),
    )