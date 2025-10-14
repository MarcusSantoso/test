"""Add tables to support friend requests and friendships.

Revision ID: 20251013_add_friendships
Revises: 20251012_add_user_columns
Create Date: 2025-10-13 12:45:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20251013_add_friendships"
down_revision: Union[str, Sequence[str], None] = "20251012_add_user_columns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "friend_requests",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("requester_id", sa.Integer(), nullable=False),
        sa.Column("receiver_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["requester_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["receiver_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "requester_id",
            "receiver_id",
            name="uq_friend_requests_requester_receiver",
        ),
    )

    op.create_table(
        "friendships",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("friend_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["friend_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("user_id < friend_id", name="ck_friendships_user_less_friend"),
        sa.UniqueConstraint("user_id", "friend_id", name="uq_friendships_user_friend"),
    )


def downgrade() -> None:
    op.drop_table("friendships")
    op.drop_table("friend_requests")
