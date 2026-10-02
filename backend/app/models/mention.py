from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Float, Index, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from backend.app.db.base import Base


class Mention(Base):
    __tablename__ = "mentions"
    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_mentions_source_external_id"),
        Index("ix_mentions_keyword_published_at", "keyword", "published_at"),
        Index("ix_mentions_source_published_at", "source", "published_at"),
        Index("ix_mentions_collected_at", "collected_at"),
        Index("ix_mentions_content_hash", "content_hash"),
        Index("ix_mentions_sentiment_topic", "sentiment", "topic"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=func.gen_random_uuid(),
    )
    source: Mapped[str] = mapped_column(Text, nullable=False)
    external_id: Mapped[str] = mapped_column(Text, nullable=False)
    keyword: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    content: Mapped[str | None] = mapped_column(Text)
    author: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    engagement: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    normalized_text: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str | None] = mapped_column(Text)
    relevance_score: Mapped[float | None] = mapped_column(Float)
    relevance_reason: Mapped[str | None] = mapped_column(Text)
    sentiment: Mapped[str | None] = mapped_column(Text)
    sentiment_score: Mapped[float | None] = mapped_column(Float)
    topic: Mapped[str | None] = mapped_column(Text)
    topic_score: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )