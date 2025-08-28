"""add first instance note field

Revision ID: 5c1b88f8f2c0
Revises: 3b35b9765f2c
Create Date: 2025-09-01 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '5c1b88f8f2c0'
down_revision: Union[str, Sequence[str], None] = '3b35b9765f2c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('calendarentry', sa.Column('first_instance_note', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('calendarentry', 'first_instance_note')
