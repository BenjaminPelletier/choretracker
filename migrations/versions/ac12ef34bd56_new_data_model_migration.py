"""new data model migration

Revision ID: ac12ef34bd56
Revises: 37f3cc068d39
Create Date: 2025-09-01 00:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union, List, Dict, Tuple
from datetime import datetime, timedelta
import calendar as cal

from alembic import op
import sqlalchemy as sa

revision: str = 'ac12ef34bd56'
down_revision: Union[str, Sequence[str], None] = '37f3cc068d39'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _apply_offset(base: datetime, offset: Dict) -> datetime:
    result = base
    if offset.get('exact_duration_seconds'):
        result += timedelta(seconds=offset['exact_duration_seconds'])
    months = (offset.get('months') or 0) + (offset.get('years') or 0) * 12
    if months:
        year = result.year + (result.month - 1 + months) // 12
        month = (result.month - 1 + months) % 12 + 1
        day = min(result.day, cal.monthrange(year, month)[1])
        result = result.replace(year=year, month=month, day=day)
    return result


def upgrade() -> None:
    op.create_table(
        'instancespecifics',
        sa.Column('entry_id', sa.Integer(), sa.ForeignKey('calendarentry.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('recurrence_id', sa.Integer(), primary_key=True),
        sa.Column('instance_index', sa.Integer(), primary_key=True),
        sa.Column('skip', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('duration_seconds', sa.Integer(), nullable=True),
        sa.Column('responsible', sa.JSON(), nullable=True),
        sa.Column('note', sa.Text(), nullable=True),
    )

    conn = op.get_bind()
    metadata = sa.MetaData()

    calendarentry = sa.Table(
        'calendarentry',
        metadata,
        sa.Column('id', sa.Integer()),
        sa.Column('recurrences', sa.JSON()),
        sa.Column('first_start', sa.DateTime()),
        sa.Column('duration_seconds', sa.Integer()),
        sa.Column('skip_first_instance', sa.Boolean()),
        sa.Column('first_instance_duration_seconds', sa.Integer()),
        sa.Column('first_instance_note', sa.Text()),
        sa.Column('first_instance_delegates', sa.JSON()),
    )

    chorecompletion = sa.Table(
        'chorecompletion',
        metadata,
        sa.Column('id', sa.Integer()),
        sa.Column('entry_id', sa.Integer()),
        sa.Column('recurrence_index', sa.Integer()),
        sa.Column('instance_index', sa.Integer()),
    )

    instancespecifics = sa.Table(
        'instancespecifics',
        metadata,
        sa.Column('entry_id', sa.Integer()),
        sa.Column('recurrence_id', sa.Integer()),
        sa.Column('instance_index', sa.Integer()),
        sa.Column('skip', sa.Boolean()),
        sa.Column('duration_seconds', sa.Integer()),
        sa.Column('responsible', sa.JSON()),
        sa.Column('note', sa.Text()),
    )

    entry_rows = conn.execute(sa.select(calendarentry)).fetchall()

    no_offset_completions: List[Tuple[int, int]] = []
    specifics_rows: Dict[Tuple[int, int, int], Dict] = {}

    for row in entry_rows:
        recurrences = row.recurrences or []
        new_recs = []
        for idx, rec in enumerate(recurrences):
            rec = dict(rec)
            has_offset = bool(rec.get('offset'))
            if not has_offset:
                rec['skipped_instances'] = [i + 1 for i in rec.get('skipped_instances', [])]
                for d in rec.get('delegations', []):
                    d['instance_index'] += 1
                for n in rec.get('notes', []):
                    n['instance_index'] += 1
                for dur in rec.get('duration_overrides', []):
                    dur['instance_index'] += 1
                if row.skip_first_instance:
                    if 0 not in rec.get('skipped_instances', []):
                        rec.setdefault('skipped_instances', []).append(0)
                if row.first_instance_duration_seconds is not None:
                    rec.setdefault('duration_overrides', []).append(
                        {
                            'instance_index': 0,
                            'duration_seconds': row.first_instance_duration_seconds,
                        }
                    )
                if row.first_instance_note is not None:
                    rec.setdefault('notes', []).append(
                        {
                            'instance_index': 0,
                            'note': row.first_instance_note,
                        }
                    )
                if row.first_instance_delegates:
                    rec.setdefault('delegations', []).append(
                        {
                            'instance_index': 0,
                            'responsible': row.first_instance_delegates,
                        }
                    )
                no_offset_completions.append((row.id, idx))

            offset = rec.get('offset')
            start = row.first_start
            if offset:
                start = _apply_offset(start, offset)
            rec['first_start'] = start.isoformat()
            rec['duration_seconds'] = row.duration_seconds
            rec['id'] = idx
            rec.pop('offset', None)

            for inst in rec.get('skipped_instances', []):
                key = (row.id, idx, inst)
                specifics_rows.setdefault(key, {}).update({'skip': True})
            for deleg in rec.get('delegations', []):
                key = (row.id, idx, deleg['instance_index'])
                specifics_rows.setdefault(key, {}).update(
                    {'responsible': deleg.get('responsible', [])}
                )
            for note in rec.get('notes', []):
                key = (row.id, idx, note['instance_index'])
                specifics_rows.setdefault(key, {}).update({'note': note.get('note')})
            for dur in rec.get('duration_overrides', []):
                key = (row.id, idx, dur['instance_index'])
                specifics_rows.setdefault(key, {}).update(
                    {'duration_seconds': dur.get('duration_seconds')}
                )

            rec.pop('skipped_instances', None)
            rec.pop('delegations', None)
            rec.pop('notes', None)
            rec.pop('duration_overrides', None)
            new_recs.append(rec)

        conn.execute(
            calendarentry.update().where(calendarentry.c.id == row.id).values(recurrences=new_recs)
        )

    for (entry_id, rec_id, inst_idx), vals in specifics_rows.items():
        conn.execute(
            instancespecifics.insert().values(
                entry_id=entry_id,
                recurrence_id=rec_id,
                instance_index=inst_idx,
                skip=vals.get('skip', False),
                duration_seconds=vals.get('duration_seconds'),
                responsible=vals.get('responsible'),
                note=vals.get('note'),
            )
        )

    for entry_id, rec_idx in no_offset_completions:
        conn.execute(
            chorecompletion.update()
            .where(
                (chorecompletion.c.entry_id == entry_id)
                & (chorecompletion.c.recurrence_index == rec_idx)
            )
            .values(instance_index=chorecompletion.c.instance_index + 1)
        )

    conn.execute(
        chorecompletion.update()
        .where(chorecompletion.c.recurrence_index == -1)
        .values(recurrence_index=0, instance_index=0)
    )

    op.alter_column('chorecompletion', 'recurrence_index', new_column_name='recurrence_id')

    op.drop_column('calendarentry', 'skip_first_instance')
    op.drop_column('calendarentry', 'first_instance_duration_seconds')
    op.drop_column('calendarentry', 'first_instance_note')
    op.drop_column('calendarentry', 'first_instance_delegates')
    op.drop_column('calendarentry', 'first_start')
    op.drop_column('calendarentry', 'duration_seconds')


def downgrade() -> None:
    op.add_column('calendarentry', sa.Column('duration_seconds', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('calendarentry', sa.Column('first_start', sa.DateTime(), nullable=True))
    op.add_column('calendarentry', sa.Column('first_instance_delegates', sa.JSON(), nullable=True))
    op.add_column('calendarentry', sa.Column('first_instance_note', sa.Text(), nullable=True))
    op.add_column('calendarentry', sa.Column('first_instance_duration_seconds', sa.Integer(), nullable=True))
    op.add_column('calendarentry', sa.Column('skip_first_instance', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.alter_column('chorecompletion', 'recurrence_id', new_column_name='recurrence_index')
    op.drop_table('instancespecifics')
    # Data downgrade not implemented
