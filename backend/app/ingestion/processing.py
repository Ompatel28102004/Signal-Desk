import hashlib
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from backend.app.ingestion.models import NormalizedMention
from backend.app.ingestion.text import html_to_text


logger = logging.getLogger(__name__)
_TRACKING_PARAMETERS = {"fbclid", "gclid", "dclid", "mc_cid", "mc_eid"}


@dataclass(frozen=True)
class ProcessingRejection:
    source: str
    external_id: str
    reason: str


@dataclass
class ProcessingBatch:
    mentions: list[NormalizedMention] = field(default_factory=list)
    rejections: list[ProcessingRejection] = field(default_factory=list)


class MentionProcessingPipeline:
    def process(
        self,
        mentions: list[NormalizedMention],
        keyword: str,
    ) -> ProcessingBatch:
        batch = ProcessingBatch()
        seen_source_ids: set[tuple[str, str]] = set()
        seen_content_hashes: set[str] = set()

        for mention in mentions:
            cleaned = clean_mention(mention)
            if cleaned.title is None and cleaned.content is None:
                self._reject(batch, cleaned, "empty_content")
                continue

            source_id = (cleaned.source, cleaned.external_id)
            if source_id in seen_source_ids:
                self._reject(batch, cleaned, "duplicate_source_external_id")
                continue
            seen_source_ids.add(source_id)

            if cleaned.content_hash and cleaned.content_hash in seen_content_hashes:
                self._reject(batch, cleaned, "duplicate_content_hash")
                continue
            if cleaned.content_hash:
                seen_content_hashes.add(cleaned.content_hash)

            score, reason = score_relevance(cleaned, keyword)
            if score == 0:
                self._reject(batch, cleaned, reason)
                continue

            accepted = cleaned.model_copy(
                update={"relevance_score": score, "relevance_reason": reason}
            )
            batch.mentions.append(accepted)
            logger.info(
                "ingestion.mention.accepted",
                extra={
                    "source_name": accepted.source,
                    "external_id": accepted.external_id,
                    "relevance_score": accepted.relevance_score,
                    "relevance_reason": accepted.relevance_reason,
                },
            )

        logger.info(
            "ingestion.processing.completed",
            extra={
                "keyword": keyword,
                "input_count": len(mentions),
                "accepted_count": len(batch.mentions),
                "rejected_count": len(batch.rejections),
            },
        )
        return batch

    @staticmethod
    def _reject(batch: ProcessingBatch, mention: NormalizedMention, reason: str) -> None:
        batch.rejections.append(
            ProcessingRejection(
                source=mention.source,
                external_id=mention.external_id,
                reason=reason,
            )
        )
        logger.info(
            "ingestion.mention.rejected",
            extra={
                "source_name": mention.source,
                "external_id": mention.external_id,
                "rejection_reason": reason,
            },
        )


def clean_mention(mention: NormalizedMention) -> NormalizedMention:
    title = html_to_text(mention.title)
    content = html_to_text(mention.content)
    canonical_text = "\n".join(part for part in (title, content) if part)
    hash_text = "\n".join(
        _canonical_text(part) for part in (title, content) if part
    )
    return mention.model_copy(
        update={
            "title": title,
            "content": content,
            "url": normalize_url(mention.url),
            "normalized_text": hash_text or None,
            "content_hash": hashlib.sha256(hash_text.encode("utf-8")).hexdigest()
            if hash_text
            else None,
        }
    )


def normalize_url(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    url = value.strip()
    try:
        parts = urlsplit(url)
        if parts.scheme.casefold() not in {"http", "https"} or not parts.hostname:
            return url
        hostname = parts.hostname.casefold()
        if ":" in hostname and not hostname.startswith("["):
            hostname = f"[{hostname}]"
        port = parts.port
        if port is not None and not (
            (parts.scheme.casefold() == "http" and port == 80)
            or (parts.scheme.casefold() == "https" and port == 443)
        ):
            hostname = f"{hostname}:{port}"
        query = [
            (key, item)
            for key, item in parse_qsl(parts.query, keep_blank_values=True)
            if not key.casefold().startswith("utm_") and key.casefold() not in _TRACKING_PARAMETERS
        ]
        return urlunsplit(
            (parts.scheme.casefold(), hostname, parts.path or "/", urlencode(query, doseq=True), "")
        )
    except ValueError:
        return url


def score_relevance(mention: NormalizedMention, keyword: str) -> tuple[float, str]:
    query = _canonical_text(keyword)
    title = _canonical_text(mention.title or "")
    content = _canonical_text(mention.content or "")
    combined = f"{title} {content}".strip()
    if not query:
        return 0.0, "empty_keyword"
    if _contains_phrase(title, query):
        return 1.0, "keyword_phrase_in_title"
    if _contains_phrase(content, query):
        return 0.9, "keyword_phrase_in_content"

    terms = set(re.findall(r"[^\W_]+", query, flags=re.UNICODE))
    text_terms = set(re.findall(r"[^\W_]+", combined, flags=re.UNICODE))
    if terms and terms.issubset(text_terms):
        return 0.8, "all_keyword_terms_present"
    if terms.intersection(text_terms):
        return 0.0, "partial_keyword_match"
    return 0.0, "keyword_not_in_content"


def _contains_phrase(text: str, phrase: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", text, flags=re.UNICODE) is not None


def _canonical_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value)
    return re.sub(r"\s+", " ", value).strip().casefold()