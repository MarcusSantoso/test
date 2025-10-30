"""Add the subscription tier column to users.

Revision ID: 20251030_add_user_tier
Revises: 20251013_add_friendships
Create Date: 2025-10-30 00:15:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20251030_add_user_tier"
down_revision: Union[str, Sequence[str], None] = "20251013_add_friendships"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Ensure each user has a tier value to support rate limits and admin UI."""
    op.add_column(
        "users",
        sa.Column(
            "tier",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "tier")
