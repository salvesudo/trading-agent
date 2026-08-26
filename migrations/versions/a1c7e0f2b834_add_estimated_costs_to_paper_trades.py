"""add estimated_costs column to paper trades

Revision ID: a1c7e0f2b834
Revises: d903390e1d8e
Create Date: 2026-08-26 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1c7e0f2b834'
down_revision: Union[str, Sequence[str], None] = 'd903390e1d8e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'paper_trades',
        sa.Column('estimated_costs', sa.Float(), nullable=False, server_default='0'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('paper_trades', 'estimated_costs')
