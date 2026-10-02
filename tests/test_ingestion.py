import hashlib
import logging
from datetime import UTC, datetime, timedelta, timezone

import pytest

from backend.app.ingestion.base import BaseSource
from backend.app.ingestion.manager import IngestionManager
from backend.app.ingestion.models import NormalizedMention, RawMention, normalize_mention


class FakeSource(BaseSource):
    def __init__(self, source_name: str, mentions: list[RawMention]) -> None:
        self._source_name = source_name
        self.mentions = mentions
        self.calls: list[tuple[str, int]] = []

    @property
    def source_name(self) -> str:
        return self._source_name

    def search(self, keyword: str, limit: int) -> list[RawMention]:
        self.calls.append((keyword, limit))
        return self.mentions[:limit]


def test_base_source_requires_adapter_implementation() -> None:
    with pytest.raises(TypeError):
        BaseSource()


def test_manager_normalizes_multiple_sources_to_one_contract() -> None:
    forum = FakeSource(
        "forum",
        [RawMention(external_id="thread-7", title="  ＮＥＷ   Launch ", content=" GREAT\nProduct ")],
    )
    news = FakeSource(
        "news",
        [RawMention.model_validate({"external_id": "story-9", "content": "A launch release"})],
    )

    result = IngestionManager([forum, news]).search("launch", limit=5)

    assert forum.calls == [("launch", 5)]
    assert news.calls == [("launch", 5)]
    assert len(result.mentions) == 2
    assert result.failures == []
    assert all(isinstance(mention, NormalizedMention) for mention in result.mentions)
    first = result.mentions[0]
    assert first.source == "forum"
    assert first.external_id == "thread-7"
    assert first.keyword == "launch"
    assert first.normalized_text == "new launch\ngreat product"
    assert first.content_hash == hashlib.sha256(b"new launch\ngreat product").hexdigest()
    assert first.collected_at.tzinfo is not None


def test_manager_keeps_successes_when_a_source_fails(caplog: pytest.LogCaptureFixture) -> None:
    class BrokenSource(FakeSource):
        def search(self, keyword: str, limit: int) -> list[RawMention]:
            raise RuntimeError("private-token-must-not-be-logged")

    working = FakeSource("working", [RawMention(external_id="ok", content="usable keyword")])
    broken = BrokenSource("broken", [])
    caplog.set_level(logging.ERROR, logger="backend.app.ingestion.manager")

    result = IngestionManager([working, broken]).search("keyword")

    assert [mention.source for mention in result.mentions] == ["working"]
    assert [(failure.source, failure.error_type) for failure in result.failures] == [
        ("broken", "RuntimeError")
    ]
    assert "private-token-must-not-be-logged" not in caplog.text
    record = next(record for record in caplog.records if record.name == "backend.app.ingestion.manager")
    assert record.source_name == "broken"
    assert record.error_type == "RuntimeError"


def test_invalid_mentions_are_skipped_and_reported() -> None:
    class InvalidSource(FakeSource):
        def search(self, keyword: str, limit: int) -> list[RawMention]:
            return [{"content": "missing external id"}, RawMention(external_id="valid", content="keyword")]

    result = IngestionManager([InvalidSource("sample", [])]).search("keyword")

    assert [mention.external_id for mention in result.mentions] == ["valid"]
    assert len(result.failures) == 1
    assert result.failures[0].source == "sample"
    assert result.failures[0].error_type == "ValidationError"


@pytest.mark.parametrize(
    ("published_at", "expected"),
    [
        (datetime(2025, 1, 1, 12), datetime(2025, 1, 1, 12, tzinfo=UTC)),
        (
            datetime(2025, 1, 1, 12, tzinfo=timezone(timedelta(hours=3))),
            datetime(2025, 1, 1, 9, tzinfo=UTC),
        ),
    ],
)
def test_normalization_canonicalizes_published_at_to_utc(
    published_at: datetime, expected: datetime
) -> None:
    mention = normalize_mention(
        "sample",
        "keyword",
        RawMention(external_id="time", published_at=published_at),
    )

    assert mention.published_at == expected
    assert mention.published_at.utcoffset() == timedelta(0)


@pytest.mark.parametrize("source_names", [["same", "same"], ["", "other"]])
def test_manager_rejects_invalid_source_registry(source_names: list[str]) -> None:
    sources = [FakeSource(name, []) for name in source_names]
    with pytest.raises(ValueError):
        IngestionManager(sources)