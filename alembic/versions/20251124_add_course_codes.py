"""Add course_codes column to professors

Revision ID: 20251124_add_course_codes
Revises: 20251114_add_prof_rev_ai
Create Date: 2025-11-24 00:00:00

"""
from alembic import op
import sqlalchemy as sa
from typing import Union, Sequence


# revision identifiers, used by Alembic.
revision: str = "20251124_add_course_codes"
down_revision: Union[str, Sequence[str], None] = "20251114_add_prof_rev_ai"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add `course_codes` text column to `professors`."""
    op.add_column("professors", sa.Column("course_codes", sa.Text(), nullable=True))


def downgrade() -> None:
    """Remove `course_codes` column from `professors`."""
    op.drop_column("professors", "course_codes")
