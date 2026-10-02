from datetime import UTC, datetime

import pytest

from backend.app.ingestion.base import BaseSource
from backend.app.ingestion.manager import IngestionManager
from backend.app.ingestion.models import NormalizedMention, RawMention, normalize_mention
from backend.app.models import Mention
from backend.app.nlp.classifier import DeterministicMentionClassifier, MentionClassifier
from backend.app.schemas.mention import MentionCreate


CLASSIFIER = DeterministicMentionClassifier()


def _classify(text: str) -> NormalizedMention:
    mention = normalize_mention(
        "test",
        "product",
        RawMention(external_id="test-1", title=text, content=None),
    )
    return CLASSIFIER.classify_many([mention])[0]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("I love this, it is excellent and helpful.", "Positive"),
        ("This is terrible, broken, and useless.", "Negative"),
        ("The package arrived on Tuesday.", "Neutral"),
        ("It is not good, the setup was terrible.", "Negative"),
        ("Not bad at all; the product is great.", "Positive"),
    ],
)
def test_sentiment_examples(text: str, expected: str) -> None:
    result = _classify(text)

    assert result.sentiment == expected
    assert 0 <= result.sentiment_score <= 1


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("The product itself is easy to use.", "Product"),
        ("The price is expensive for this subscription.", "Pricing"),
        ("Customer support and the agent were helpful.", "Customer Service"),
        ("The build quality is durable and reliable.", "Quality"),
        ("Compared to competitors, this alternative is better.", "Competitors"),
        ("I have a complaint about this issue.", "Complaints"),
        ("The new feature adds useful functionality.", "Features"),
        ("The package arrived on Tuesday.", "Other"),
    ],
)
def test_topic_examples(text: str, expected: str) -> None:
    result = _classify(text)

    assert result.topic == expected
    assert 0 <= result.topic_score <= 1


def test_classifier_processes_batches_and_preserves_order() -> None:
    mentions = [
        normalize_mention(
            "test",
            "keyword",
            RawMention(external_id=f"{index}", title=text),
        )
        for index, text in enumerate(("Great product", "Broken device", "New product"))
    ]

    classified = CLASSIFIER.classify_many(mentions)

    assert [item.external_id for item in classified] == ["0", "1", "2"]
    assert [item.sentiment for item in classified] == ["Positive", "Negative", "Neutral"]


def test_manager_accepts_replaceable_classifier_service() -> None:
    class Source(BaseSource):
        @property
        def source_name(self) -> str:
            return "source"

        def search(self, keyword: str, limit: int) -> list[RawMention]:
            return [RawMention(external_id="one", title="Great product")]

    class FixedClassifier(MentionClassifier):
        def __init__(self) -> None:
            self.seen: list[NormalizedMention] = []

        def classify_many(self, mentions: list[NormalizedMention]) -> list[NormalizedMention]:
            self.seen = list(mentions)
            return [
                item.model_copy(
                    update={
                        "sentiment": "Positive",
                        "sentiment_score": 1.0,
                        "topic": "Product",
                        "topic_score": 1.0,
                    }
                )
                for item in mentions
            ]

    classifier = FixedClassifier()
    result = IngestionManager([Source()], classifier=classifier).search("product")

    assert len(classifier.seen) == 1
    assert result.mentions[0].sentiment == "Positive"
    assert result.mentions[0].topic == "Product"
    assert result.mentions[0].topic_score == 1.0


def test_classification_fields_are_in_the_stored_mention_contract() -> None:
    mention = _classify("Excellent product")

    assert mention.sentiment in {"Positive", "Neutral", "Negative"}
    assert mention.sentiment_score is not None
    assert mention.topic in {
        "Product",
        "Pricing",
        "Customer Service",
        "Quality",
        "Competitors",
        "Complaints",
        "Features",
        "Other",
    }
    assert mention.topic_score is not None
    assert mention.published_at is None or mention.published_at.tzinfo == UTC

    insert_payload = MentionCreate(
        source=mention.source,
        external_id=mention.external_id,
        keyword=mention.keyword,
        sentiment=mention.sentiment,
        sentiment_score=mention.sentiment_score,
        topic=mention.topic,
        topic_score=mention.topic_score,
    )
    assert insert_payload.topic_score == mention.topic_score
    assert "topic_score" in Mention.__table__.c