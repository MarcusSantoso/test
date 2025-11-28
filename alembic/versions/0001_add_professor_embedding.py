"""Add embedding column to professors

Revision ID: 0001_add_professor_embedding
Revises: 20251124_add_course_codes
Create Date: 2025-11-27 00:00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from typing import Union, Sequence

# revision identifiers, used by Alembic.
revision: str = "0001_add_professor_embedding"
down_revision: Union[str, Sequence[str], None] = "1151f0c2b1fc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add `embedding` JSONB column to `professors`."""
    op.add_column(
        "professors",
        sa.Column("embedding", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    """Remove `embedding` column from `professors`."""
    op.drop_column("professors", "embedding")
