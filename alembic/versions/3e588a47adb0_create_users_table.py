"""create users table

Revision ID: 3e588a47adb0
Revises: 
Create Date: 2025-09-26 01:45:57.067024

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3e588a47adb0'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
            'users',
            sa.Column('name', sa.String()),
            sa.PrimaryKeyConstraint('name')
            )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('users')
