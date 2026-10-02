"""Store the rationale for accepted relevance scores."""

from alembic import op
import sqlalchemy as sa


revision = "0002_add_relevance_reason"
down_revision = "0001_create_mentions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("mentions", sa.Column("relevance_reason", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("mentions", "relevance_reason")