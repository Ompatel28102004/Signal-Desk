"""Create the social listening mentions table."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0001_create_mentions"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mentions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("source", sa.String(length=80), nullable=False),
        sa.Column("external_id", sa.String(length=512), nullable=False),
        sa.Column("keyword", sa.String(length=255), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("author", sa.String(length=255), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("collected_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("engagement", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("normalized_text", sa.Text(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("relevance_score", sa.Float(), nullable=True),
        sa.Column("sentiment", sa.String(length=32), nullable=True),
        sa.Column("sentiment_score", sa.Float(), nullable=True),
        sa.Column("topic", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_mentions"),
        sa.UniqueConstraint("source", "external_id", name="uq_mentions_source_external_id"),
    )
    op.create_index("ix_mentions_keyword_published_at", "mentions", ["keyword", "published_at"])
    op.create_index("ix_mentions_source_published_at", "mentions", ["source", "published_at"])
    op.create_index("ix_mentions_collected_at", "mentions", ["collected_at"])
    op.create_index("ix_mentions_content_hash", "mentions", ["content_hash"])
    op.create_index("ix_mentions_sentiment_topic", "mentions", ["sentiment", "topic"])


def downgrade() -> None:
    op.drop_index("ix_mentions_sentiment_topic", table_name="mentions")
    op.drop_index("ix_mentions_content_hash", table_name="mentions")
    op.drop_index("ix_mentions_collected_at", table_name="mentions")
    op.drop_index("ix_mentions_source_published_at", table_name="mentions")
    op.drop_index("ix_mentions_keyword_published_at", table_name="mentions")
    op.drop_table("mentions")