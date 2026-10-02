"""Widen variable mention fields to TEXT without truncating stored data."""

from alembic import op
import sqlalchemy as sa


revision = "0004_use_text_columns"
down_revision = "0003_add_topic_score"
branch_labels = None
depends_on = None


_COLUMNS = (
    ("source", 80, False),
    ("external_id", 512, False),
    ("keyword", 255, False),
    ("author", 255, True),
    ("content_hash", 64, True),
    ("relevance_reason", 255, True),
    ("sentiment", 32, True),
    ("topic", 255, True),
)


def upgrade() -> None:
    for name, length, nullable in _COLUMNS:
        op.alter_column(
            "mentions",
            name,
            existing_type=sa.String(length=length),
            type_=sa.Text(),
            existing_nullable=nullable,
        )


def downgrade() -> None:
    for name, length, nullable in reversed(_COLUMNS):
        op.alter_column(
            "mentions",
            name,
            existing_type=sa.Text(),
            type_=sa.String(length=length),
            existing_nullable=nullable,
        )