from __future__ import annotations

from datetime import datetime, timedelta
from enum import Enum
from dataclasses import dataclass
from heapq import heappush, heappop
import calendar as cal
from typing import Iterator, List, Optional

from sqlmodel import Column, Field, Session, SQLModel, select
from sqlalchemy import JSON, ForeignKey, Integer, delete

from .time_utils import get_now, ensure_tz


class RecurrenceType(str, Enum):
    OneTime = "OneTime"
    Weekly = "Weekly"
    MonthlyDayOfMonth = "MonthlyDayOfMonth"
    MonthlyDayOfWeek = "MonthlyDayOfWeek"
    AnnualDayOfMonth = "AnnualDayOfMonth"


class CalendarEntryType(str, Enum):
    Event = "Event"
    Chore = "Chore"
    Reminder = "Reminder"


class Delegation(SQLModel):
    instance_index: int
    responsible: List[str] = Field(default_factory=list)


class InstanceNote(SQLModel):
    instance_index: int
    note: str


class InstanceDuration(SQLModel):
    instance_index: int
    duration_seconds: int = Field(gt=0)

class Recurrence(SQLModel):
    id: int
    type: RecurrenceType
    first_start: datetime
    duration_seconds: int = Field(gt=0)
    responsible: List[str] = Field(default_factory=list)


class CalendarEntry(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str
    description: str = ""
    type: CalendarEntryType
    recurrences: List[Recurrence] = Field(default_factory=list, sa_column=Column(JSON))
    none_after: Optional[datetime] = None
    none_before: Optional[datetime] = None
    responsible: List[str] = Field(default_factory=list, sa_column=Column(JSON))
    managers: List[str] = Field(default_factory=list, sa_column=Column(JSON))
    previous_entry: Optional[int] = Field(
        default=None, foreign_key="calendarentry.id"
    )
    next_entry: Optional[int] = Field(
        default=None, foreign_key="calendarentry.id"
    )


class InstanceSpecifics(SQLModel, table=True):
    entry_id: int = Field(
        sa_column=Column(
            Integer, ForeignKey("calendarentry.id", ondelete="CASCADE"), primary_key=True
        )
    )
    recurrence_id: int = Field(primary_key=True)
    instance_index: int = Field(primary_key=True)
    skip: bool = Field(default=False)
    duration_seconds: Optional[int] = None
    responsible: Optional[List[str]] = Field(
        default=None, sa_column=Column(JSON)
    )
    note: Optional[str] = None


def _load_instance_specifics(session: Session, entry: CalendarEntry) -> None:
    specs = session.exec(
        select(InstanceSpecifics).where(InstanceSpecifics.entry_id == entry.id)
    ).all()
    rec_map = {rec.id: rec for rec in entry.recurrences}
    for spec in specs:
        rec = rec_map.get(spec.recurrence_id)
        if not rec:
            continue
        if spec.skip:
            skipped = getattr(rec, "skipped_instances", [])
            skipped.append(spec.instance_index)
            setattr(rec, "skipped_instances", skipped)
        if spec.responsible is not None:
            delegations = getattr(rec, "delegations", [])
            delegations.append(
                Delegation(instance_index=spec.instance_index, responsible=spec.responsible)
            )
            setattr(rec, "delegations", delegations)
        if spec.note is not None:
            notes = getattr(rec, "notes", [])
            notes.append(InstanceNote(instance_index=spec.instance_index, note=spec.note))
            setattr(rec, "notes", notes)
        if spec.duration_seconds is not None:
            overrides = getattr(rec, "duration_overrides", [])
            overrides.append(
                InstanceDuration(
                    instance_index=spec.instance_index,
                    duration_seconds=spec.duration_seconds,
                )
            )
            setattr(rec, "duration_overrides", overrides)


def _store_instance_specifics(session: Session, entry: CalendarEntry) -> None:
    session.exec(delete(InstanceSpecifics).where(InstanceSpecifics.entry_id == entry.id))
    for rec in entry.recurrences:
        spec_map: dict[int, InstanceSpecifics] = {}
        for idx in getattr(rec, "skipped_instances", []):
            spec_map.setdefault(
                idx,
                InstanceSpecifics(
                    entry_id=entry.id, recurrence_id=rec.id, instance_index=idx
                ),
            ).skip = True
        for deleg in getattr(rec, "delegations", []):
            spec_map.setdefault(
                deleg.instance_index,
                InstanceSpecifics(
                    entry_id=entry.id,
                    recurrence_id=rec.id,
                    instance_index=deleg.instance_index,
                ),
            ).responsible = deleg.responsible
        for note in getattr(rec, "notes", []):
            spec_map.setdefault(
                note.instance_index,
                InstanceSpecifics(
                    entry_id=entry.id,
                    recurrence_id=rec.id,
                    instance_index=note.instance_index,
                ),
            ).note = note.note
        for dur in getattr(rec, "duration_overrides", []):
            spec_map.setdefault(
                dur.instance_index,
                InstanceSpecifics(
                    entry_id=entry.id,
                    recurrence_id=rec.id,
                    instance_index=dur.instance_index,
                ),
            ).duration_seconds = dur.duration_seconds
        for spec in spec_map.values():
            session.add(spec)


class CalendarEntryStore:
    def __init__(self, engine):
        self.engine = engine

    def create(self, entry: CalendarEntry) -> None:
        if not entry.managers:
            raise ValueError("CalendarEntry must have at least one manager")
        if not entry.recurrences:
            entry.recurrences = [Recurrence(type=RecurrenceType.OneTime)]
        with Session(self.engine) as session:
            recs = entry.recurrences
            entry.recurrences = [
                Recurrence.model_validate(r).model_dump() for r in recs
            ]
            session.add(entry)
            session.commit()
            entry.recurrences = recs
            _store_instance_specifics(session, entry)
            session.commit()

    def get(self, entry_id: int) -> Optional[CalendarEntry]:
        with Session(self.engine) as session:
            entry = session.get(CalendarEntry, entry_id)
            if entry:
                entry.recurrences = [
                    rec if isinstance(rec, Recurrence) else Recurrence.model_validate(rec)
                    for rec in entry.recurrences
                ]
                for rec in entry.recurrences:
                    rec.first_start = ensure_tz(rec.first_start)
                entry.none_after = ensure_tz(entry.none_after)
                entry.none_before = ensure_tz(entry.none_before)
                _load_instance_specifics(session, entry)
            return entry

    def update(self, entry_id: int, new_data: CalendarEntry) -> None:
        if not new_data.managers:
            raise ValueError("CalendarEntry must have at least one manager")
        if not new_data.recurrences:
            new_data.recurrences = [Recurrence(type=RecurrenceType.OneTime)]
        with Session(self.engine) as session:
            entry = session.get(CalendarEntry, entry_id)
            if not entry:
                return
            entry.title = new_data.title
            entry.description = new_data.description
            entry.type = new_data.type
            recs = new_data.recurrences
            entry.recurrences = [
                Recurrence.model_validate(r).model_dump() for r in recs
            ]
            entry.none_after = new_data.none_after
            entry.none_before = new_data.none_before
            entry.responsible = new_data.responsible
            entry.managers = new_data.managers
            session.add(entry)
            session.commit()
            entry.recurrences = recs
            _store_instance_specifics(session, entry)
            session.commit()

    def list_entries(self) -> List[CalendarEntry]:
        with Session(self.engine) as session:
            entries = session.exec(select(CalendarEntry)).all()
            for entry in entries:
                entry.recurrences = [
                    rec if isinstance(rec, Recurrence) else Recurrence.model_validate(rec)
                    for rec in entry.recurrences
                ]
                for rec in entry.recurrences:
                    rec.first_start = ensure_tz(rec.first_start)
                entry.none_after = ensure_tz(entry.none_after)
                entry.none_before = ensure_tz(entry.none_before)
                _load_instance_specifics(session, entry)
            return entries

    def delete(self, entry_id: int) -> bool:
        with Session(self.engine) as session:
            entry = session.get(CalendarEntry, entry_id)
            if not entry:
                return False
            entry.recurrences = [
                rec if isinstance(rec, Recurrence) else Recurrence.model_validate(rec)
                for rec in entry.recurrences
            ]
            _load_instance_specifics(session, entry)
            has_delegations = any(
                getattr(rec, "delegations", []) for rec in entry.recurrences
            )
            has_completions = (
                session.exec(
                    select(ChoreCompletion.id).where(ChoreCompletion.entry_id == entry_id)
                ).first()
                is not None
            )
            if has_delegations or has_completions:
                return False
            session.delete(entry)
            session.commit()
            return True

    def split(
        self, entry_id: int, split_time: datetime
    ) -> Optional[CalendarEntry]:
        """Split a CalendarEntry at ``split_time``.

        Returns the newly created CalendarEntry or ``None`` if ``entry_id``
        does not exist.
        """
        with Session(self.engine) as session:
            entry = session.get(CalendarEntry, entry_id)
            if not entry:
                return None
            # Ensure Recurrence objects
            entry.recurrences = [
                rec if isinstance(rec, Recurrence) else Recurrence.model_validate(rec)
                for rec in entry.recurrences
            ]
            for rec in entry.recurrences:
                rec.first_start = ensure_tz(rec.first_start)
            entry.none_after = ensure_tz(entry.none_after)
            entry.none_before = ensure_tz(entry.none_before)
            _load_instance_specifics(session, entry)

            # Copy of entry for time period calculations
            original = CalendarEntry.model_validate(entry.model_dump())
            original.recurrences = [
                r if isinstance(r, Recurrence) else Recurrence.model_validate(r)
                for r in original.recurrences
            ]
            _load_instance_specifics(session, original)

            # Create new entry as a copy
            new_entry = CalendarEntry.model_validate(entry.model_dump())
            new_entry.id = None
            new_entry.none_before = split_time
            new_entry.recurrences = [
                Recurrence.model_validate(r.model_dump()) for r in entry.recurrences
            ]

            # Move skips and delegations
            for idx, rec in enumerate(entry.recurrences):
                new_rec = new_entry.recurrences[idx]
                keep_skips: list[int] = []
                move_skips: list[int] = []
                for sidx in getattr(rec, "skipped_instances", []):
                    period = find_time_period(original, rec.id, sidx, include_skipped=True)
                    if period and period.start >= split_time:
                        move_skips.append(sidx)
                    else:
                        keep_skips.append(sidx)
                setattr(rec, "skipped_instances", keep_skips)
                setattr(new_rec, "skipped_instances", move_skips)

                keep_del: list[Delegation] = []
                move_del: list[Delegation] = []
                for d in getattr(rec, "delegations", []):
                    period = find_time_period(
                        original, rec.id, d.instance_index, include_skipped=True
                    )
                    if period and period.start >= split_time:
                        move_del.append(d)
                    else:
                        keep_del.append(d)
                setattr(rec, "delegations", keep_del)
                setattr(new_rec, "delegations", move_del)

                keep_notes: list[InstanceNote] = []
                move_notes: list[InstanceNote] = []
                for n in getattr(rec, "notes", []):
                    period = find_time_period(
                        original, rec.id, n.instance_index, include_skipped=True
                    )
                    if period and period.start >= split_time:
                        move_notes.append(n)
                    else:
                        keep_notes.append(n)
                setattr(rec, "notes", keep_notes)
                setattr(new_rec, "notes", move_notes)

                keep_dur: list[InstanceDuration] = []
                move_dur: list[InstanceDuration] = []
                for d in getattr(rec, "duration_overrides", []):
                    period = find_time_period(
                        original, rec.id, d.instance_index, include_skipped=True
                    )
                    if period and period.start >= split_time:
                        move_dur.append(d)
                    else:
                        keep_dur.append(d)
                setattr(rec, "duration_overrides", keep_dur)
                setattr(new_rec, "duration_overrides", move_dur)

            # Adjust boundaries
            entry.none_after = split_time - timedelta(minutes=1)

            session.add(entry)
            session.add(new_entry)
            session.commit()

            # Link entries
            entry.next_entry = new_entry.id
            new_entry.previous_entry = entry.id
            session.add(entry)
            session.add(new_entry)
            session.commit()

            # Store instance specifics
            _store_instance_specifics(session, entry)
            _store_instance_specifics(session, new_entry)

            # Move completions
            comps = session.exec(
                select(ChoreCompletion).where(ChoreCompletion.entry_id == entry_id)
            ).all()
            for comp in comps:
                period = find_time_period(
                    original, comp.recurrence_id, comp.instance_index, include_skipped=True
                )
                if period and period.start >= split_time:
                    comp.entry_id = new_entry.id
                    session.add(comp)
            session.commit()

            # Ensure recurrences are Recurrence objects for return
            new_entry.recurrences = [
                r if isinstance(r, Recurrence) else Recurrence.model_validate(r)
                for r in new_entry.recurrences
            ]
            return new_entry


class ChoreCompletion(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    entry_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("calendarentry.id", ondelete="CASCADE"),
            index=True,
        )
    )
    recurrence_id: int
    instance_index: int
    completed_by: str
    completed_at: datetime = Field(default_factory=get_now)


class ChoreCompletionStore:
    def __init__(self, engine):
        self.engine = engine

    def get(
        self, entry_id: int, recurrence_id: int, instance_index: int
    ) -> Optional[ChoreCompletion]:
        with Session(self.engine) as session:
            stmt = select(ChoreCompletion).where(
                (ChoreCompletion.entry_id == entry_id)
                & (ChoreCompletion.recurrence_id == recurrence_id)
                & (ChoreCompletion.instance_index == instance_index)
            )
            comp = session.exec(stmt).first()
            if comp:
                comp.completed_at = ensure_tz(comp.completed_at)
            return comp

    def create(
        self,
        entry_id: int,
        recurrence_id: int,
        instance_index: int,
        user: str,
        completed_at: datetime | None = None,
    ) -> None:
        completion = ChoreCompletion(
            entry_id=entry_id,
            recurrence_id=recurrence_id,
            instance_index=instance_index,
            completed_by=user,
            completed_at=completed_at or get_now(),
        )
        with Session(self.engine) as session:
            session.add(completion)
            session.commit()

    def delete(self, entry_id: int, recurrence_id: int, instance_index: int) -> None:
        with Session(self.engine) as session:
            stmt = select(ChoreCompletion).where(
                (ChoreCompletion.entry_id == entry_id)
                & (ChoreCompletion.recurrence_id == recurrence_id)
                & (ChoreCompletion.instance_index == instance_index)
            )
            comp = session.exec(stmt).first()
            if comp:
                session.delete(comp)
                session.commit()

    def list_for_entry(self, entry_id: int) -> List[ChoreCompletion]:
        with Session(self.engine) as session:
            stmt = select(ChoreCompletion).where(ChoreCompletion.entry_id == entry_id)
            comps = session.exec(stmt).all()
            for comp in comps:
                comp.completed_at = ensure_tz(comp.completed_at)
            return comps


@dataclass
class TimePeriod:
    start: datetime
    end: datetime
    recurrence_id: int
    instance_index: int


def _add_months_skip(dt: datetime, months: int) -> datetime:
    """Add months to a datetime, skipping months where the day doesn't exist."""
    result = dt
    step = 1 if months >= 0 else -1
    for _ in range(abs(months)):
        year = result.year
        month = result.month + step
        if month > 12:
            month = 1
            year += 1
        elif month < 1:
            month = 12
            year -= 1
        day = result.day
        while True:
            try:
                result = result.replace(year=year, month=month, day=day)
                break
            except ValueError:
                month += step
                if month > 12:
                    month = 1
                    year += 1
                elif month < 1:
                    month = 12
                    year -= 1
    return result


def _next_monthly_day_of_week(dt: datetime) -> datetime:
    nth = (dt.day - 1) // 7 + 1
    weekday = dt.weekday()
    year, month = dt.year, dt.month
    while True:
        month += 1
        if month > 12:
            month = 1
            year += 1
        first_weekday, days_in_month = cal.monthrange(year, month)
        day = 1 + ((weekday - first_weekday) % 7) + (nth - 1) * 7
        if day > days_in_month:
            continue
        return dt.replace(year=year, month=month, day=day)
def _advance(start: datetime, rtype: RecurrenceType) -> Optional[datetime]:
    if rtype == RecurrenceType.OneTime:
        return None
    if rtype == RecurrenceType.Weekly:
        return start + timedelta(weeks=1)
    if rtype == RecurrenceType.MonthlyDayOfMonth:
        return _add_months_skip(start, 1)
    if rtype == RecurrenceType.MonthlyDayOfWeek:
        return _next_monthly_day_of_week(start)
    if rtype == RecurrenceType.AnnualDayOfMonth:
        return _add_months_skip(start, 12)
    raise ValueError(f"Unsupported recurrence type: {rtype}")


def _recurrence_generator(
    entry: CalendarEntry, rec: Recurrence, include_skipped: bool
) -> Iterator[TimePeriod]:
    none_after = entry.none_after
    none_before = entry.none_before
    start = rec.first_start
    instance = 0
    while start and (not none_after or start <= none_after):
        if (
            (not none_before or start >= none_before)
            and (
                include_skipped
                or instance not in getattr(rec, "skipped_instances", [])
            )
        ):
            dur = duration_for(entry, rec.id, instance)
            yield TimePeriod(
                start=start,
                end=start + dur,
                recurrence_id=rec.id,
                instance_index=instance,
            )
        instance += 1
        start = _advance(start, rec.type)


def enumerate_time_periods(
    entry: CalendarEntry, include_skipped: bool = False
) -> Iterator[TimePeriod]:
    heap: List[tuple[datetime, int, Iterator[TimePeriod], TimePeriod]] = []
    for rec in entry.recurrences:
        if not isinstance(rec, Recurrence):
            rec = Recurrence.model_validate(rec)
        gen = _recurrence_generator(entry, rec, include_skipped)
        first = next(gen, None)
        if first:
            heappush(heap, (first.start, rec.id, gen, first))

    while heap:
        _, rid, gen, period = heappop(heap)
        yield period
        nxt = next(gen, None)
        if nxt:
            heappush(heap, (nxt.start, rid, gen, nxt))


def find_time_period(
    entry: CalendarEntry,
    recurrence_id: int,
    instance_index: int,
    include_skipped: bool = False,
) -> Optional[TimePeriod]:
    for period in enumerate_time_periods(entry, include_skipped=include_skipped):
        if (
            period.recurrence_id == recurrence_id
            and period.instance_index == instance_index
        ):
            return period
    return None


def responsible_for(
    entry: CalendarEntry, recurrence_id: int, instance_index: int
) -> List[str]:
    rec = next((r for r in entry.recurrences if r.id == recurrence_id), None)
    if rec:
        if not isinstance(rec, Recurrence):
            rec = Recurrence.model_validate(rec)
        for d in getattr(rec, "delegations", []):
            if not isinstance(d, Delegation):
                d = Delegation.model_validate(d)
            if d.instance_index == instance_index:
                return d.responsible
        if rec.responsible:
            return rec.responsible
    return entry.responsible


def find_delegation(
    entry: CalendarEntry, recurrence_id: int, instance_index: int
) -> Optional[Delegation]:
    rec = next((r for r in entry.recurrences if r.id == recurrence_id), None)
    if rec:
        if not isinstance(rec, Recurrence):
            rec = Recurrence.model_validate(rec)
        for d in getattr(rec, "delegations", []):
            if not isinstance(d, Delegation):
                d = Delegation.model_validate(d)
            if d.instance_index == instance_index:
                return d
    return None


def find_instance_note(
    entry: CalendarEntry, recurrence_id: int, instance_index: int
) -> Optional[InstanceNote]:
    rec = next((r for r in entry.recurrences if r.id == recurrence_id), None)
    if rec:
        if not isinstance(rec, Recurrence):
            rec = Recurrence.model_validate(rec)
        for n in getattr(rec, "notes", []):
            if not isinstance(n, InstanceNote):
                n = InstanceNote.model_validate(n)
            if n.instance_index == instance_index:
                return n
    return None


def find_instance_duration(
    entry: CalendarEntry, recurrence_id: int, instance_index: int
) -> Optional[InstanceDuration]:
    rec = next((r for r in entry.recurrences if r.id == recurrence_id), None)
    if rec:
        if not isinstance(rec, Recurrence):
            rec = Recurrence.model_validate(rec)
        for d in getattr(rec, "duration_overrides", []):
            if not isinstance(d, InstanceDuration):
                d = InstanceDuration.model_validate(d)
            if d.instance_index == instance_index:
                return d
    return None


def duration_for(
    entry: CalendarEntry, recurrence_id: int, instance_index: int
) -> timedelta:
    override = find_instance_duration(entry, recurrence_id, instance_index)
    if override:
        return timedelta(seconds=override.duration_seconds)
    rec = next((r for r in entry.recurrences if r.id == recurrence_id), None)
    if rec:
        if not isinstance(rec, Recurrence):
            rec = Recurrence.model_validate(rec)
        return timedelta(seconds=rec.duration_seconds)
    return timedelta(0)

