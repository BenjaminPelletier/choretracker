"""move entry timing into recurrence

Revision ID: d1d5f1b2c3a4
Revises: 37f3cc068d39
Create Date: 2025-09-01 00:00:01.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import json
from datetime import datetime
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "d1d5f1b2c3a4"
down_revision: Union[str, Sequence[str], None] = "37f3cc068d39"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    cols = {col["name"] for col in insp.get_columns("calendarentry")}
    if "first_start" in cols and "duration_seconds" in cols:
        rows = conn.execute(
            sa.text(
                "SELECT id, first_start, duration_seconds, recurrences FROM calendarentry"
            )
        ).mappings().all()
        for row in rows:
            recurrences = row["recurrences"] or []
            if isinstance(recurrences, str):
                recurrences = json.loads(recurrences)
            first_start = row["first_start"]
            if first_start is not None and not isinstance(first_start, str):
                first_start = first_start.isoformat()
            recurrences.insert(
                0,
                {
                    "type": "OneTime",
                    "first_start": first_start,
                    "duration_seconds": row["duration_seconds"],
                    "offset": None,
                    "skipped_instances": [],
                    "responsible": [],
                    "delegations": [],
                    "notes": [],
                    "duration_overrides": [],
                },
            )
            conn.execute(
                sa.text(
                    "UPDATE calendarentry SET recurrences = :rec WHERE id = :id"
                ),
                {"rec": json.dumps(recurrences), "id": row["id"]},
            )
        conn.execute(
            sa.text(
                "UPDATE chorecompletion SET recurrence_index = recurrence_index + 1 WHERE recurrence_index >= 0"
            )
        )
        with op.batch_alter_table("calendarentry") as batch_op:
            batch_op.drop_column("first_start")
            batch_op.drop_column("duration_seconds")

def downgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    cols = {col["name"] for col in insp.get_columns("calendarentry")}
    if "first_start" not in cols and "duration_seconds" not in cols:
        with op.batch_alter_table("calendarentry") as batch_op:
            batch_op.add_column(sa.Column("first_start", sa.DateTime(), nullable=True))
            batch_op.add_column(sa.Column("duration_seconds", sa.Integer(), nullable=True))
        rows = conn.execute(
            sa.text("SELECT id, recurrences FROM calendarentry")
        ).mappings().all()
        for row in rows:
            recurrences = row["recurrences"] or []
            if isinstance(recurrences, str):
                recurrences = json.loads(recurrences)
            first_start = None
            duration_seconds = None
            if recurrences:
                first = recurrences[0]
                first_start = first.get("first_start")
                duration_seconds = first.get("duration_seconds")
                recurrences = recurrences[1:]
            if isinstance(first_start, str):
                first_start = datetime.fromisoformat(first_start)
            conn.execute(
                sa.text(
                    "UPDATE calendarentry SET first_start = :fs, duration_seconds = :dur, recurrences = :rec WHERE id = :id"
                ),
                {
                    "fs": first_start,
                    "dur": duration_seconds,
                    "rec": json.dumps(recurrences),
                    "id": row["id"],
                },
            )
        conn.execute(
            sa.text(
                "UPDATE chorecompletion SET recurrence_index = recurrence_index - 1 WHERE recurrence_index >= 0"
            )
        )
