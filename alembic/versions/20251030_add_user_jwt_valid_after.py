"""Add jwt_valid_after column for token invalidation support.

Revision ID: 20251030_add_user_jwt_valid
Revises: 20251030_add_user_tier
Create Date: 2025-10-30 00:20:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20251030_add_user_jwt_valid"
down_revision: Union[str, Sequence[str], None] = "20251030_add_user_tier"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Allow per-user JWT invalidation timestamps."""
    op.add_column(
        "users",
        sa.Column(
            "jwt_valid_after",
            sa.DateTime(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "jwt_valid_after")
