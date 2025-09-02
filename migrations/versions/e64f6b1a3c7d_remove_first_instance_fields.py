"""remove first instance fields from calendarentry

Revision ID: e64f6b1a3c7d
Revises: d1d5f1b2c3a4
Create Date: 2025-09-01 00:00:02.000000
"""

from __future__ import annotations

from typing import Sequence, Union
import json

from alembic import op
import sqlalchemy as sa

revision: str = "e64f6b1a3c7d"
down_revision: Union[str, Sequence[str], None] = "d1d5f1b2c3a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    cols = {c["name"] for c in insp.get_columns("calendarentry")}
    needed = {
        "first_instance_delegates",
        "first_instance_note",
        "first_instance_duration_seconds",
        "skip_first_instance",
    }
    if needed.issubset(cols):
        rows = conn.execute(
            sa.text(
                "SELECT id, recurrences, first_instance_delegates, "
                "first_instance_note, first_instance_duration_seconds, "
                "skip_first_instance FROM calendarentry"
            )
        ).mappings().all()
        for row in rows:
            recurrences = row["recurrences"] or []
            if isinstance(recurrences, str):
                recurrences = json.loads(recurrences)
            if not recurrences:
                recurrences = [
                    {
                        "type": "OneTime",
                        "first_start": None,
                        "duration_seconds": 0,
                        "offset": None,
                        "skipped_instances": [],
                        "responsible": [],
                        "delegations": [],
                        "notes": [],
                        "duration_overrides": [],
                    }
                ]
            rec0 = recurrences[0]
            delegates = row["first_instance_delegates"]
            if isinstance(delegates, str):
                try:
                    delegates = json.loads(delegates)
                except Exception:
                    delegates = []
            if delegates:
                rec0.setdefault("delegations", []).append(
                    {
                        "instance_index": 0,
                        "responsible": delegates,
                    }
                )
            if row["first_instance_note"]:
                rec0.setdefault("notes", []).append(
                    {"instance_index": 0, "note": row["first_instance_note"]}
                )
            if row["first_instance_duration_seconds"] is not None:
                rec0.setdefault("duration_overrides", []).append(
                    {
                        "instance_index": 0,
                        "duration_seconds": row["first_instance_duration_seconds"],
                    }
                )
            if row["skip_first_instance"]:
                rec0.setdefault("skipped_instances", [])
                if 0 not in rec0["skipped_instances"]:
                    rec0["skipped_instances"].append(0)
            recurrences[0] = rec0
            conn.execute(
                sa.text(
                    "UPDATE calendarentry SET recurrences = :rec WHERE id = :id"
                ),
                {"rec": json.dumps(recurrences), "id": row["id"]},
            )
        with op.batch_alter_table("calendarentry") as batch_op:
            batch_op.drop_column("first_instance_delegates")
            batch_op.drop_column("first_instance_note")
            batch_op.drop_column("first_instance_duration_seconds")
            batch_op.drop_column("skip_first_instance")


def downgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    cols = {c["name"] for c in insp.get_columns("calendarentry")}
    needed = {
        "first_instance_delegates",
        "first_instance_note",
        "first_instance_duration_seconds",
        "skip_first_instance",
    }
    if not needed.issubset(cols):
        with op.batch_alter_table("calendarentry") as batch_op:
            batch_op.add_column(
                sa.Column("first_instance_delegates", sa.JSON(), nullable=True)
            )
            batch_op.add_column(
                sa.Column("first_instance_note", sa.Text(), nullable=True)
            )
            batch_op.add_column(
                sa.Column(
                    "first_instance_duration_seconds", sa.Integer(), nullable=True
                )
            )
            batch_op.add_column(
                sa.Column(
                    "skip_first_instance",
                    sa.Boolean(),
                    nullable=False,
                    server_default="0",
                )
            )
        rows = conn.execute(
            sa.text("SELECT id, recurrences FROM calendarentry")
        ).mappings().all()
        for row in rows:
            recurrences = row["recurrences"] or []
            if isinstance(recurrences, str):
                recurrences = json.loads(recurrences)
            delegates = None
            note = None
            duration = None
            skip = False
            if recurrences:
                rec0 = recurrences[0]
                dels = []
                for d in rec0.get("delegations", []):
                    if d.get("instance_index") == 0:
                        delegates = d.get("responsible")
                    else:
                        dels.append(d)
                rec0["delegations"] = dels
                notes = []
                for n in rec0.get("notes", []):
                    if n.get("instance_index") == 0:
                        note = n.get("note")
                    else:
                        notes.append(n)
                rec0["notes"] = notes
                overrides = []
                for o in rec0.get("duration_overrides", []):
                    if o.get("instance_index") == 0:
                        duration = o.get("duration_seconds")
                    else:
                        overrides.append(o)
                rec0["duration_overrides"] = overrides
                skips = [s for s in rec0.get("skipped_instances", []) if s != 0]
                skip = 0 in rec0.get("skipped_instances", [])
                rec0["skipped_instances"] = skips
                recurrences[0] = rec0
            conn.execute(
                sa.text(
                    "UPDATE calendarentry SET recurrences = :rec, "
                    "first_instance_delegates = :d, first_instance_note = :n, "
                    "first_instance_duration_seconds = :dur, skip_first_instance = :s "
                    "WHERE id = :id"
                ),
                {
                    "rec": json.dumps(recurrences),
                    "d": json.dumps(delegates) if delegates else None,
                    "n": note,
                    "dur": duration,
                    "s": skip,
                    "id": row["id"],
                },
            )
