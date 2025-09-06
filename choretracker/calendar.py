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
    instance_specifics: dict[int, InstanceSpecifics] = Field(
        default_factory=dict, exclude=True
    )


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

Recurrence.model_rebuild()


def _load_instance_specifics(session: Session, entry: CalendarEntry) -> None:
    specs = session.exec(
        select(InstanceSpecifics).where(InstanceSpecifics.entry_id == entry.id)
    ).all()
    rec_map = {rec.id: rec for rec in entry.recurrences}
    for spec in specs:
        rec = rec_map.get(spec.recurrence_id)
        if not rec:
            continue
        rec.instance_specifics[spec.instance_index] = InstanceSpecifics.model_validate(
            spec.model_dump()
        )


def _store_instance_specifics(session: Session, entry: CalendarEntry) -> None:
    session.exec(delete(InstanceSpecifics).where(InstanceSpecifics.entry_id == entry.id))
    for rec in entry.recurrences:
        for spec in rec.instance_specifics.values():
            if not isinstance(spec, InstanceSpecifics):
                spec = InstanceSpecifics.model_validate(spec)
            db_spec = InstanceSpecifics(
                entry_id=entry.id,
                recurrence_id=rec.id,
                instance_index=spec.instance_index,
            )
            if spec.skip:
                db_spec.skip = True
            if spec.responsible is not None:
                db_spec.responsible = spec.responsible
            if spec.note is not None:
                db_spec.note = spec.note
            if spec.duration_seconds is not None:
                db_spec.duration_seconds = spec.duration_seconds
            session.add(db_spec)


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
                any(spec.responsible for spec in rec.instance_specifics.values())
                for rec in entry.recurrences
            )
            has_completions = (
                session.exec(
                    select(ChoreCompletion.id).where(ChoreCompletion.entry_id == entry_id)
                ).first()
                is not None
            )
            if has_delegations or has_completions:
                return False
            prev_id = entry.previous_entry
            next_id = entry.next_entry
            affected_prev = session.exec(
                select(CalendarEntry).where(CalendarEntry.previous_entry == entry_id)
            ).all()
            for e in affected_prev:
                e.previous_entry = prev_id
                session.add(e)
            affected_next = session.exec(
                select(CalendarEntry).where(CalendarEntry.next_entry == entry_id)
            ).all()
            for e in affected_next:
                e.next_entry = next_id
                session.add(e)
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

            # Move instance specifics
            for idx, rec in enumerate(entry.recurrences):
                new_rec = new_entry.recurrences[idx]
                keep_specs: dict[int, InstanceSpecifics] = {}
                move_specs: dict[int, InstanceSpecifics] = {}
                for sidx, spec in rec.instance_specifics.items():
                    period = find_time_period(original, rec.id, sidx, include_skipped=True)
                    if period and period.start >= split_time:
                        move_specs[sidx] = spec
                    else:
                        keep_specs[sidx] = spec
                rec.instance_specifics = keep_specs
                new_rec.instance_specifics = move_specs

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

            # Ensure Recurrence objects after commit
            entry.recurrences = [
                r if isinstance(r, Recurrence) else Recurrence.model_validate(r)
                for r in entry.recurrences
            ]
            new_entry.recurrences = [
                r if isinstance(r, Recurrence) else Recurrence.model_validate(r)
                for r in new_entry.recurrences
            ]

            # Move completions before storing instance specifics
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

            # Store instance specifics
            _store_instance_specifics(session, entry)
            _store_instance_specifics(session, new_entry)
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
    specs = rec.instance_specifics
    while start and (not none_after or start <= none_after):
        if (
            (not none_before or start >= none_before)
            and (
                include_skipped
                or not (specs.get(instance) and specs[instance].skip)
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


def has_single_instance(entry: CalendarEntry) -> bool:
    """Return ``True`` if ``entry`` has only a single instance.

    This checks the number of generated time periods for the entry and treats
    skipped instances as still counting toward the total.  Only a single
    ``next`` call is made after the first period to avoid generating the entire
    sequence.
    """

    gen = enumerate_time_periods(entry, include_skipped=True)
    first = next(gen, None)
    if not first:
        return True
    second = next(gen, None)
    return second is None


def find_time_period(
    entry: CalendarEntry,
    recurrence_id: int,
    instance_index: int,
    include_skipped: bool = False,
) -> Optional[TimePeriod]:
    # Ensure instance specifics are detached models
    for i, rec in enumerate(entry.recurrences):
        if not isinstance(rec, Recurrence):
            rec = Recurrence.model_validate(rec)
            entry.recurrences[i] = rec
        rec.instance_specifics = {
            idx: InstanceSpecifics.model_validate(
                spec.model_dump() if isinstance(spec, InstanceSpecifics) else spec
            )
            for idx, spec in rec.instance_specifics.items()
        }
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
        spec = rec.instance_specifics.get(instance_index)
        if spec:
            if not isinstance(spec, InstanceSpecifics):
                spec = InstanceSpecifics.model_validate(spec)
            if spec.responsible is not None:
                return spec.responsible
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
        spec = rec.instance_specifics.get(instance_index)
        if spec:
            if not isinstance(spec, InstanceSpecifics):
                spec = InstanceSpecifics.model_validate(spec)
            if spec.responsible is not None:
                return Delegation(
                    instance_index=instance_index, responsible=spec.responsible
                )
    return None


def find_instance_note(
    entry: CalendarEntry, recurrence_id: int, instance_index: int
) -> Optional[InstanceNote]:
    rec = next((r for r in entry.recurrences if r.id == recurrence_id), None)
    if rec:
        if not isinstance(rec, Recurrence):
            rec = Recurrence.model_validate(rec)
        spec = rec.instance_specifics.get(instance_index)
        if spec:
            if not isinstance(spec, InstanceSpecifics):
                spec = InstanceSpecifics.model_validate(spec)
            if spec.note is not None:
                return InstanceNote(instance_index=instance_index, note=spec.note)
    return None


def find_instance_duration(
    entry: CalendarEntry, recurrence_id: int, instance_index: int
) -> Optional[InstanceDuration]:
    rec = next((r for r in entry.recurrences if r.id == recurrence_id), None)
    if rec:
        if not isinstance(rec, Recurrence):
            rec = Recurrence.model_validate(rec)
        spec = rec.instance_specifics.get(instance_index)
        if spec:
            if not isinstance(spec, InstanceSpecifics):
                spec = InstanceSpecifics.model_validate(spec)
            if spec.duration_seconds is not None:
                return InstanceDuration(
                    instance_index=instance_index,
                    duration_seconds=spec.duration_seconds,
                )
    return None


def is_instance_skipped(
    entry: CalendarEntry, recurrence_id: int, instance_index: int
) -> bool:
    rec = next((r for r in entry.recurrences if r.id == recurrence_id), None)
    if rec:
        if not isinstance(rec, Recurrence):
            rec = Recurrence.model_validate(rec)
        spec = rec.instance_specifics.get(instance_index)
        if spec:
            if not isinstance(spec, InstanceSpecifics):
                spec = InstanceSpecifics.model_validate(spec)
            return bool(spec.skip)
    return False


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

