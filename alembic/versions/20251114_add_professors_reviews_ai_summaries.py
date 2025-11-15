"""Add professors, reviews and AI summaries tables

Revision ID: 20251114_add_prof_rev_ai
Revises: 20251030_add_user_jwt_valid
Create Date: 2025-11-14 00:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20251114_add_prof_rev_ai"
down_revision: Union[str, Sequence[str], None] = "20251030_add_user_jwt_valid"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create professors, reviews and ai_summaries tables."""
    op.create_table(
        "professors",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("department", sa.String(), nullable=True),
        sa.Column("rmp_url", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "reviews",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("prof_id", sa.Integer(), sa.ForeignKey("professors.id", ondelete="CASCADE"), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("source", sa.String(), nullable=True),
        sa.Column("timestamp", sa.DateTime(), nullable=True),
        sa.Column("rating", sa.Integer(), nullable=True),
    )

    op.create_table(
        "ai_summaries",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("prof_id", sa.Integer(), sa.ForeignKey("professors.id", ondelete="CASCADE"), nullable=False),
        sa.Column("pros", sa.JSON(), nullable=True),
        sa.Column("cons", sa.JSON(), nullable=True),
        sa.Column("neutral", sa.JSON(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    # ensure one summary per professor
    op.create_unique_constraint("uq_ai_summaries_prof_id", "ai_summaries", ["prof_id"])


def downgrade() -> None:
    """Drop ai_summaries, reviews and professors."""
    op.drop_constraint("uq_ai_summaries_prof_id", "ai_summaries", type_="unique")
    op.drop_table("ai_summaries")
    op.drop_table("reviews")
    op.drop_table("professors")
