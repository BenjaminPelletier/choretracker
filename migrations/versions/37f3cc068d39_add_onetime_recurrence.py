"""ensure calendar entries have a recurrence

Revision ID: 37f3cc068d39
Revises: c1a5c0d5e4f4
Create Date: 2025-09-01 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import json

revision: str = '37f3cc068d39'
down_revision: Union[str, Sequence[str], None] = 'c1a5c0d5e4f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    value = json.dumps([{"type": "OneTime"}])
    op.execute(
        sa.text(
            "UPDATE calendarentry SET recurrences = :value "
            "WHERE recurrences IS NULL OR recurrences = '[]'"
        ),
        {"value": value},
    )


def downgrade() -> None:
    value = json.dumps([{"type": "OneTime"}])
    op.execute(
        sa.text(
            "UPDATE calendarentry SET recurrences = '[]' "
            "WHERE recurrences = :value"
        ),
        {"value": value},
    )
