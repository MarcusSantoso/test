"""merge ai_summary_snapshot and add_course_codes heads

Revision ID: 1151f0c2b1fc
Revises: 20251118_ai_summary_snapshot, 20251124_add_course_codes
Create Date: 2025-11-24 21:28:54.632341

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1151f0c2b1fc'
down_revision: Union[str, Sequence[str], None] = ('20251118_ai_summary_snapshot', '20251124_add_course_codes')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
