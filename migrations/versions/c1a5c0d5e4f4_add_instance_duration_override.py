"""add instance duration override

Revision ID: c1a5c0d5e4f4
Revises: 5c1b88f8f2c0
Create Date: 2025-09-01 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'c1a5c0d5e4f4'
down_revision: Union[str, Sequence[str], None] = '5c1b88f8f2c0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('calendarentry', sa.Column('first_instance_duration_seconds', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('calendarentry', 'first_instance_duration_seconds')
