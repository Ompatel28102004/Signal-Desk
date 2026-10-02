import logging
from collections.abc import Iterable

from pydantic import ValidationError

from backend.app.ingestion.base import BaseSource
from backend.app.ingestion.models import (
    IngestionResult,
    NormalizedMention,
    RawMention,
    SourceFailure,
    normalize_mention,
)
from backend.app.ingestion.processing import MentionProcessingPipeline
from backend.app.nlp.classifier import DeterministicMentionClassifier, MentionClassifier


logger = logging.getLogger(__name__)


class IngestionManager:
    def __init__(
        self,
        sources: Iterable[BaseSource],
        processor: MentionProcessingPipeline | None = None,
        classifier: MentionClassifier | None = None,
    ) -> None:
        self._sources = tuple(sources)
        self._processor = processor or MentionProcessingPipeline()
        self._classifier = classifier or DeterministicMentionClassifier()
        source_names = [source.source_name.strip() for source in self._sources]
        if any(not name for name in source_names):
            raise ValueError("source_name must not be empty")
        if len(source_names) != len(set(source_names)):
            raise ValueError("source names must be unique")

    def search(
        self,
        keyword: str,
        limit: int = 100,
        *,
        classify: bool = True,
    ) -> IngestionResult:
        keyword = keyword.strip()
        if not keyword:
            raise ValueError("keyword must not be empty")
        if limit < 1:
            raise ValueError("limit must be positive")

        result = IngestionResult()
        for source in self._sources:
            source_name = source.source_name.strip()
            if not source.enabled:
                result.disabled_sources.append(source.disabled_message)
                logger.info(
                    "ingestion.source.disabled",
                    extra={"source_name": source_name, "status_message": source.disabled_message},
                )
                continue
            try:
                raw_mentions = source.search(keyword, limit)
            except Exception as error:
                self._record_failure(result, source_name, type(error).__name__, keyword)
                continue

            normalized: list[NormalizedMention] = []
            for index, raw_mention in enumerate(raw_mentions):
                try:
                    raw = RawMention.model_validate(raw_mention)
                    normalized.append(normalize_mention(source_name, keyword, raw))
                except (ValidationError, TypeError, ValueError) as error:
                    self._record_failure(
                        result,
                        source_name,
                        type(error).__name__,
                        keyword,
                        item_index=index,
                    )

            result.mentions.extend(normalized)
            logger.info(
                "ingestion.source.completed",
                extra={
                    "source_name": source_name,
                    "keyword": keyword,
                    "result_count": len(normalized),
                    "requested_limit": limit,
                },
            )

        processing = self._processor.process(result.mentions, keyword)
        result.mentions = processing.mentions
        if classify:
            result.mentions = self.classify_many(result.mentions)
        logger.info(
            "ingestion.search.completed",
            extra={
                "keyword": keyword,
                "source_count": len(self._sources),
                "mention_count": len(result.mentions),
                "rejected_count": len(processing.rejections),
                "failure_count": len(result.failures),
            },
        )
        return result

    @property
    def sources(self) -> tuple[BaseSource, ...]:
        return self._sources

    def classify_many(self, mentions: list[NormalizedMention]) -> list[NormalizedMention]:
        return self._classifier.classify_many(mentions)

    @staticmethod
    def _record_failure(
        result: IngestionResult,
        source_name: str,
        error_type: str,
        keyword: str,
        *,
        item_index: int | None = None,
    ) -> None:
        result.failures.append(SourceFailure(source=source_name, error_type=error_type))
        logger.error(
            "ingestion.source.failed",
            extra={
                "source_name": source_name,
                "keyword": keyword,
                "error_type": error_type,
                "item_index": item_index,
            },
        )