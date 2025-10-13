"""Add id, email, and password columns to users table.

Revision ID: 20251012_add_user_columns
Revises: 3e588a47adb0
Create Date: 2025-10-12 23:15:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20251012_add_user_columns"
down_revision: Union[str, Sequence[str], None] = "3e588a47adb0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add surrogate id and credential columns to the users table."""
    op.drop_constraint("users_pkey", "users", type_="primary")

    op.execute("ALTER TABLE users ADD COLUMN id SERIAL")
    op.execute("ALTER TABLE users ADD PRIMARY KEY (id)")
    op.create_unique_constraint("uq_users_name", "users", ["name"])

    op.add_column("users", sa.Column("email", sa.String(), nullable=True))
    op.add_column("users", sa.Column("password", sa.String(), nullable=True))

    op.execute("UPDATE users SET email = '' WHERE email IS NULL")
    op.execute("UPDATE users SET password = '' WHERE password IS NULL")

    op.alter_column("users", "email", nullable=False)
    op.alter_column("users", "password", nullable=False)


def downgrade() -> None:
    """Restore the original users schema with name as the primary key."""
    op.alter_column("users", "password", nullable=True)
    op.alter_column("users", "email", nullable=True)

    op.drop_column("users", "password")
    op.drop_column("users", "email")

    op.drop_constraint("uq_users_name", "users", type_="unique")

    op.drop_constraint("users_pkey", "users", type_="primary")
    op.drop_column("users", "id")
    op.execute("DROP SEQUENCE IF EXISTS users_id_seq")

    op.create_primary_key("users_pkey", "users", ["name"])
