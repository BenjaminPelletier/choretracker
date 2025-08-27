"""add first instance delegation and skip fields

Revision ID: 9b77df98c5a2
Revises: 281a93177d8a
Create Date: 2025-09-01 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '9b77df98c5a2'
down_revision: Union[str, Sequence[str], None] = '281a93177d8a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('calendarentry', sa.Column('first_instance_delegates', sa.JSON(), nullable=True))
    op.add_column('calendarentry', sa.Column('skip_first_instance', sa.Boolean(), nullable=False, server_default='0'))


def downgrade() -> None:
    op.drop_column('calendarentry', 'skip_first_instance')
    op.drop_column('calendarentry', 'first_instance_delegates')
