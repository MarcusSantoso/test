"""Add review_count_snapshot to ai_summaries

Revision ID: 20251118_ai_summary_snapshot
Revises: 20251116_add_ai_summary_history
Create Date: 2025-11-18 00:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20251118_ai_summary_snapshot"
down_revision: Union[str, Sequence[str], None] = "20251116_add_ai_summary_history"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "ai_summaries",
        sa.Column("review_count_snapshot", sa.Integer(), nullable=True),
    )
    op.execute(
        "UPDATE ai_summaries SET review_count_snapshot = 0 WHERE review_count_snapshot IS NULL"
    )


def downgrade() -> None:
    op.drop_column("ai_summaries", "review_count_snapshot")
