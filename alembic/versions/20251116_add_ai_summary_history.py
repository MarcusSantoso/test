"""Add AI summary history table.

Revision ID: 20251116_add_ai_summary_history
Revises: 20251114_add_professors_reviews_ai_summaries
Create Date: 2025-11-16 10:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20251116_add_ai_summary_history"
down_revision: Union[str, None] = "20251114_add_prof_rev_ai"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ai_summary_history",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source_text", sa.Text(), nullable=False),
        sa.Column("summary_text", sa.Text(), nullable=False),
        sa.Column("context", sa.Text(), nullable=True),
        sa.Column("raw_response", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("ai_summary_history")
