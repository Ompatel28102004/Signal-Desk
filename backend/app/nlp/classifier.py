import re
import unicodedata
from collections.abc import Sequence
from typing import Protocol

from backend.app.ingestion.models import NormalizedMention


SENTIMENT_LEXICON: dict[str, int] = {
    "amazing": 2,
    "awful": -2,
    "bad": -1,
    "broken": -2,
    "delightful": 2,
    "disappointed": -2,
    "disappointing": -2,
    "easy": 1,
    "excellent": 2,
    "fail": -1,
    "frustrated": -1,
    "frustrating": -1,
    "good": 1,
    "great": 2,
    "hate": -2,
    "helpful": 1,
    "horrible": -2,
    "impressed": 1,
    "love": 2,
    "loved": 2,
    "poor": -1,
    "perfect": 2,
    "recommend": 1,
    "reliable": 1,
    "satisfied": 2,
    "slow": -1,
    "smooth": 1,
    "terrible": -2,
    "unhappy": -1,
    "useless": -2,
    "worst": -2,
}

NEGATORS = {"no", "not", "never", "hardly", "isn't", "wasn't", "don't", "didn't"}

TOPIC_TERMS: dict[str, tuple[str, ...]] = {
    "Product": ("product", "item", "device", "software", "platform"),
    "Pricing": ("price", "pricing", "cost", "expensive", "cheap", "subscription", "fee", "discount"),
    "Customer Service": (
        "customer service",
        "customer support",
        "support",
        "helpdesk",
        "agent",
        "representative",
    ),
    "Quality": (
        "quality",
        "reliable",
        "reliability",
        "durable",
        "durability",
        "defect",
        "broken",
        "damaged",
        "build quality",
    ),
    "Competitors": ("competitor", "competitors", "alternative", "versus", "vs", "compared to"),
    "Complaints": (
        "complaint",
        "complaints",
        "complain",
        "issue",
        "problem",
        "unacceptable",
        "never again",
    ),
    "Features": (
        "feature",
        "features",
        "functionality",
        "capability",
        "integration",
        "option",
        "design",
        "update",
    ),
}


class MentionClassifier(Protocol):
    def classify_many(self, mentions: Sequence[NormalizedMention]) -> list[NormalizedMention]:
        """Classify a batch and return records with sentiment/topic fields populated."""


class DeterministicMentionClassifier:
    """Small local lexicon/rule classifier; no network or model download is required."""

    def classify_many(self, mentions: Sequence[NormalizedMention]) -> list[NormalizedMention]:
        return [self.classify(mention) for mention in mentions]

    def classify(self, mention: NormalizedMention) -> NormalizedMention:
        text = _canonical_text(mention.normalized_text or " ".join(
            part for part in (mention.title, mention.content) if part
        ))
        sentiment, sentiment_score = _classify_sentiment(text)
        topic, topic_score = _classify_topic(text)
        return mention.model_copy(
            update={
                "sentiment": sentiment,
                "sentiment_score": sentiment_score,
                "topic": topic,
                "topic_score": topic_score,
            }
        )


def _classify_sentiment(text: str) -> tuple[str, float]:
    tokens = re.findall(r"[^\W_]+(?:['’][^\W_]+)?", text, flags=re.UNICODE)
    positive = 0
    negative = 0
    for index, token in enumerate(tokens):
        weight = SENTIMENT_LEXICON.get(token)
        if weight is None:
            continue
        preceding = tokens[max(0, index - 3) : index]
        if any(negator in preceding for negator in NEGATORS):
            weight *= -1
        if weight > 0:
            positive += weight
        else:
            negative += abs(weight)

    polarity = positive - negative
    total_evidence = positive + negative
    if polarity > 0:
        sentiment = "Positive"
        confidence = 0.5 + 0.5 * polarity / total_evidence
    elif polarity < 0:
        sentiment = "Negative"
        confidence = 0.5 + 0.5 * abs(polarity) / total_evidence
    else:
        sentiment = "Neutral"
        confidence = 0.5 if total_evidence else 0.75
    return sentiment, round(min(confidence, 1.0), 3)


def _classify_topic(text: str) -> tuple[str, float]:
    scores = {
        category: sum(_count_phrase(text, term) for term in terms)
        for category, terms in TOPIC_TERMS.items()
    }
    top_category = max(scores, key=scores.get)
    top_score = scores[top_category]
    if top_score == 0:
        return "Other", 0.5
    total = sum(scores.values())
    return top_category, round(top_score / total, 3)


def _count_phrase(text: str, phrase: str) -> int:
    pattern = rf"(?<!\w){re.escape(phrase)}(?!\w)"
    return sum(1 for _ in re.finditer(pattern, text, flags=re.UNICODE))


def _canonical_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"\s+", " ", normalized).strip()