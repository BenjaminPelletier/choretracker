"""apply entry first_start and duration to recurrences

Revision ID: 16f872f43a3c
Revises: 37f3cc068d39
Create Date: 2025-09-03 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import json
from itertools import islice, zip_longest

from choretracker.calendar import (
    CalendarEntry,
    CalendarEntryType,
    Recurrence,
    RecurrenceType,
    enumerate_time_periods,
    _advance,
)
from choretracker.time_utils import ensure_tz

revision: str = '16f872f43a3c'
down_revision: Union[str, Sequence[str], None] = '37f3cc068d39'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    metadata = sa.MetaData()
    calendarentry = sa.Table(
        "calendarentry",
        metadata,
        sa.Column("id", sa.Integer),
        sa.Column("first_start", sa.DateTime()),
        sa.Column("duration_seconds", sa.Integer()),
        sa.Column("recurrences", sa.JSON()),
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

        entry_before = CalendarEntry(
            id=entry_id,
            title="",
            description="",
            type=CalendarEntryType.Event,
            first_start=first_start,
            duration_seconds=duration,
            recurrences=[Recurrence.model_validate(r) for r in recurrences],
        )
        periods_before = [
            (
                ensure_tz(p.start),
                ensure_tz(p.end),
                p.recurrence_index,
                p.instance_index,
            )
            for p in islice(enumerate_time_periods(entry_before), 1000)
        ]

        updated = []
        for rec in recurrences:
            if not isinstance(rec, dict):
                rec = dict(rec)
            rtype = RecurrenceType(rec["type"])
            start = first_start if rec.get("offset") else _advance(first_start, rtype)
            if start:
                rec["first_start"] = start.isoformat()
            else:
                rec.pop("first_start", None)
            rec["duration_seconds"] = duration
            updated.append(rec)

        entry_after = CalendarEntry(
            id=entry_id,
            title="",
            description="",
            type=CalendarEntryType.Event,
            first_start=first_start,
            duration_seconds=duration,
            recurrences=[Recurrence.model_validate(r) for r in updated],
        )
        periods_after = [
            (
                ensure_tz(p.start),
                ensure_tz(p.end),
                p.recurrence_index,
                p.instance_index,
            )
            for p in islice(enumerate_time_periods(entry_after), 1000)
        ]
        for i, (before, after) in enumerate(zip_longest(periods_before, periods_after)):
            if before != after:
                raise AssertionError(
                    f"TimePeriods changed for CalendarEntry {entry_id} at index {i}: before {before}, after {after}"
                )

        conn.execute(
            sa.update(calendarentry)
            .where(calendarentry.c.id == entry_id)
            .values(recurrences=updated)
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
            .values(recurrences=recurrences)
        )
