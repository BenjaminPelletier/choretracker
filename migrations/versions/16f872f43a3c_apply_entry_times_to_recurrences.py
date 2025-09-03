"""apply entry first_start and duration to recurrences

Revision ID: 16f872f43a3c
Revises: 37f3cc068d39
Create Date: 2025-09-03 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import json

revision: str = '16f872f43a3c'
down_revision: Union[str, Sequence[str], None] = '37f3cc068d39'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    metadata = sa.MetaData()
    calendarentry = sa.Table(
        'calendarentry',
        metadata,
        sa.Column('id', sa.Integer),
        sa.Column('first_start', sa.DateTime()),
        sa.Column('duration_seconds', sa.Integer()),
        sa.Column('recurrences', sa.JSON()),
    )
    rows = conn.execute(
        sa.select(
            calendarentry.c.id,
            calendarentry.c.first_start,
            calendarentry.c.duration_seconds,
            calendarentry.c.recurrences,
        )
    ).fetchall()
    for entry_id, first_start, duration, recurrences in rows:
        if not recurrences:
            continue
        if isinstance(recurrences, str):
            recurrences = json.loads(recurrences)
        start_str = first_start if isinstance(first_start, str) else first_start.isoformat()
        updated = []
        for rec in recurrences:
            if not isinstance(rec, dict):
                rec = dict(rec)
            rec['first_start'] = start_str
            rec['duration_seconds'] = duration
            updated.append(rec)
        conn.execute(
            sa.update(calendarentry)
            .where(calendarentry.c.id == entry_id)
            .values(recurrences=json.dumps(updated))
        )


def downgrade() -> None:
    conn = op.get_bind()
    metadata = sa.MetaData()
    calendarentry = sa.Table(
        'calendarentry',
        metadata,
        sa.Column('id', sa.Integer),
        sa.Column('recurrences', sa.JSON()),
    )
    rows = conn.execute(
        sa.select(calendarentry.c.id, calendarentry.c.recurrences)
    ).fetchall()
    for entry_id, recurrences in rows:
        if not recurrences:
            continue
        if isinstance(recurrences, str):
            recurrences = json.loads(recurrences)
        for rec in recurrences:
            if isinstance(rec, dict):
                rec.pop('first_start', None)
                rec.pop('duration_seconds', None)
        conn.execute(
            sa.update(calendarentry)
            .where(calendarentry.c.id == entry_id)
            .values(recurrences=json.dumps(recurrences))
        )
