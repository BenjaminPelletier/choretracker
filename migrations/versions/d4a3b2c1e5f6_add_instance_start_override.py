"""add instance start override

Revision ID: d4a3b2c1e5f6
Revises: ac12ef34bd56
Create Date: 2025-09-01 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'd4a3b2c1e5f6'
down_revision: Union[str, Sequence[str], None] = 'ac12ef34bd56'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('instancespecifics', sa.Column('start', sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column('instancespecifics', 'start')
