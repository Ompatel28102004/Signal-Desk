"""Store deterministic topic-classification confidence."""

from alembic import op
import sqlalchemy as sa


revision = "0003_add_topic_score"
down_revision = "0002_add_relevance_reason"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("mentions", sa.Column("topic_score", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("mentions", "topic_score")