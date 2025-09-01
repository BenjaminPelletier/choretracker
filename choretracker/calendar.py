from __future__ import annotations

from datetime import datetime, timedelta
from enum import Enum
from dataclasses import dataclass
from heapq import heappush, heappop
import calendar as cal
from typing import Iterator, List, Optional

from sqlmodel import Column, Field, Session, SQLModel, select
from sqlalchemy import JSON, ForeignKey, Integer
from pydantic import ConfigDict

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


class Offset(SQLModel):
    exact_duration_seconds: Optional[int] = None
    months: Optional[int] = None
    years: Optional[int] = None


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
    type: RecurrenceType
    first_start: Optional[datetime] = None
    duration_seconds: Optional[int] = None
    offset: Optional[Offset] = None
    skipped_instances: List[int] = Field(default_factory=list)
    responsible: List[str] = Field(default_factory=list)
    delegations: List[Delegation] = Field(default_factory=list)
    notes: List[InstanceNote] = Field(default_factory=list)
    duration_overrides: List[InstanceDuration] = Field(default_factory=list)

    @property
    def duration(self) -> timedelta:
        return timedelta(seconds=self.duration_seconds or 0)

    @duration.setter
    def duration(self, value: timedelta) -> None:
        self.duration_seconds = int(value.total_seconds())


class CalendarEntry(SQLModel, table=True):
    model_config = ConfigDict(extra="allow")
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

    @property
    def first_start(self) -> datetime:
        if not self.recurrences:
            raise AttributeError("No recurrences")
        rec = self.recurrences[0]
        if not isinstance(rec, Recurrence):
            rec = Recurrence.model_validate(rec)
            self.recurrences[0] = rec
        return rec.first_start  # type: ignore

    @first_start.setter
    def first_start(self, value: datetime) -> None:
        if not self.recurrences:
            self.recurrences = [
                Recurrence(
                    type=RecurrenceType.OneTime,
                    first_start=value,
                    duration_seconds=0,
                )
            ]
        else:
            rec = self.recurrences[0]
            if not isinstance(rec, Recurrence):
                rec = Recurrence.model_validate(rec)
                self.recurrences[0] = rec
            rec.first_start = value

    @property
    def duration_seconds(self) -> int:
        if not self.recurrences:
            raise AttributeError("No recurrences")
        rec = self.recurrences[0]
        if not isinstance(rec, Recurrence):
            rec = Recurrence.model_validate(rec)
            self.recurrences[0] = rec
        return rec.duration_seconds or 0

    @duration_seconds.setter
    def duration_seconds(self, value: int) -> None:
        if not self.recurrences:
            self.recurrences = [
                Recurrence(
                    type=RecurrenceType.OneTime,
                    first_start=get_now(),
                    duration_seconds=value,
                )
            ]
        else:
            rec = self.recurrences[0]
            if not isinstance(rec, Recurrence):
                rec = Recurrence.model_validate(rec)
                self.recurrences[0] = rec
            rec.duration_seconds = value

    @property
    def duration(self) -> timedelta:
        return timedelta(seconds=self.duration_seconds)

    @duration.setter
    def duration(self, value: timedelta) -> None:
        self.duration_seconds = int(value.total_seconds())

    def __init__(self, **data):  # type: ignore[override]
        first_start = data.pop("first_start", None)
        duration_seconds = data.pop("duration_seconds", None)
        super().__init__(**data)
        if first_start is not None:
            self.first_start = first_start
        if duration_seconds is not None:
            self.duration_seconds = duration_seconds


class CalendarEntryStore:
    def __init__(self, engine):
        self.engine = engine

    def create(self, entry: CalendarEntry) -> None:
        if not entry.managers:
            raise ValueError("CalendarEntry must have at least one manager")
        if not entry.recurrences:
            raise ValueError("CalendarEntry must have at least one recurrence")
        with Session(self.engine) as session:
            session.add(entry)
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
                    if rec.first_start:
                        rec.first_start = ensure_tz(rec.first_start)
                entry.none_after = ensure_tz(entry.none_after)
                entry.none_before = ensure_tz(entry.none_before)
            return entry

    def update(self, entry_id: int, new_data: CalendarEntry) -> None:
        if not new_data.managers:
            raise ValueError("CalendarEntry must have at least one manager")
        if not new_data.recurrences:
            raise ValueError("CalendarEntry must have at least one recurrence")
        with Session(self.engine) as session:
            entry = session.get(CalendarEntry, entry_id)
            if not entry:
                return
            entry.title = new_data.title
            entry.description = new_data.description
            entry.type = new_data.type
            entry.recurrences = new_data.recurrences
            entry.none_after = new_data.none_after
            entry.none_before = new_data.none_before
            entry.responsible = new_data.responsible
            entry.managers = new_data.managers
            session.add(entry)
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
                    if rec.first_start:
                        rec.first_start = ensure_tz(rec.first_start)
                entry.none_after = ensure_tz(entry.none_after)
                entry.none_before = ensure_tz(entry.none_before)
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
            has_delegations = any(rec.delegations for rec in entry.recurrences)
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
            entry.first_start = ensure_tz(entry.first_start)
            entry.none_after = ensure_tz(entry.none_after)
            entry.none_before = ensure_tz(entry.none_before)

            # Copy of entry for time period calculations
            original = CalendarEntry.model_validate(entry.model_dump())
            original.recurrences = [
                r if isinstance(r, Recurrence) else Recurrence.model_validate(r)
                for r in original.recurrences
            ]

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
                for sidx in rec.skipped_instances:
                    period = find_time_period(original, idx, sidx, include_skipped=True)
                    if period and period.start >= split_time:
                        move_skips.append(sidx)
                    else:
                        keep_skips.append(sidx)
                rec.skipped_instances = list(keep_skips)
                new_rec.skipped_instances = list(move_skips)

                keep_del: list[Delegation] = []
                move_del: list[Delegation] = []
                for d in rec.delegations:
                    period = find_time_period(original, idx, d.instance_index, include_skipped=True)
                    if period and period.start >= split_time:
                        move_del.append(d)
                    else:
                        keep_del.append(d)
                rec.delegations = keep_del
                new_rec.delegations = move_del

                keep_notes: list[InstanceNote] = []
                move_notes: list[InstanceNote] = []
                for n in rec.notes:
                    period = find_time_period(
                        original, idx, n.instance_index, include_skipped=True
                    )
                    if period and period.start >= split_time:
                        move_notes.append(n)
                    else:
                        keep_notes.append(n)
                rec.notes = keep_notes
                new_rec.notes = move_notes

                keep_dur: list[InstanceDuration] = []
                move_dur: list[InstanceDuration] = []
                for d in rec.duration_overrides:
                    period = find_time_period(
                        original, idx, d.instance_index, include_skipped=True
                    )
                    if period and period.start >= split_time:
                        move_dur.append(d)
                    else:
                        keep_dur.append(d)
                rec.duration_overrides = keep_dur
                new_rec.duration_overrides = move_dur

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

            # Move completions
            comps = session.exec(
                select(ChoreCompletion).where(ChoreCompletion.entry_id == entry_id)
            ).all()
            for comp in comps:
                period = find_time_period(
                    original, comp.recurrence_index, comp.instance_index, include_skipped=True
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
    recurrence_index: int
    instance_index: int
    completed_by: str
    completed_at: datetime = Field(default_factory=get_now)


class ChoreCompletionStore:
    def __init__(self, engine):
        self.engine = engine

    def get(
        self, entry_id: int, recurrence_index: int, instance_index: int
    ) -> Optional[ChoreCompletion]:
        with Session(self.engine) as session:
            stmt = select(ChoreCompletion).where(
                (ChoreCompletion.entry_id == entry_id)
                & (ChoreCompletion.recurrence_index == recurrence_index)
                & (ChoreCompletion.instance_index == instance_index)
            )
            comp = session.exec(stmt).first()
            if comp:
                comp.completed_at = ensure_tz(comp.completed_at)
            return comp

    def create(
        self,
        entry_id: int,
        recurrence_index: int,
        instance_index: int,
        user: str,
        completed_at: datetime | None = None,
    ) -> None:
        completion = ChoreCompletion(
            entry_id=entry_id,
            recurrence_index=recurrence_index,
            instance_index=instance_index,
            completed_by=user,
            completed_at=completed_at or get_now(),
        )
        with Session(self.engine) as session:
            session.add(completion)
            session.commit()

    def delete(self, entry_id: int, recurrence_index: int, instance_index: int) -> None:
        with Session(self.engine) as session:
            stmt = select(ChoreCompletion).where(
                (ChoreCompletion.entry_id == entry_id)
                & (ChoreCompletion.recurrence_index == recurrence_index)
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
    recurrence_index: int
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


def _apply_offset(base: datetime, offset: Offset) -> datetime:
    result = base
    if offset.exact_duration_seconds:
        result += timedelta(seconds=offset.exact_duration_seconds)
    months = (offset.months or 0) + (offset.years or 0) * 12
    if months:
        result = _add_months_skip(result, months)
    return result


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
    entry: CalendarEntry, rec: Recurrence, rindex: int, include_skipped: bool
) -> Iterator[TimePeriod]:
    none_after = entry.none_after
    none_before = entry.none_before
    start = rec.first_start or entry.first_start
    if rec.offset:
        start = _apply_offset(start, rec.offset)
    instance = 0
    while start and (not none_after or start <= none_after):
        if (
            (not none_before or start >= none_before)
            and (include_skipped or instance not in rec.skipped_instances)
        ):
            dur = duration_for(entry, rindex, instance)
            yield TimePeriod(
                start=start,
                end=start + dur,
                recurrence_index=rindex,
                instance_index=instance,
            )
        instance += 1
        start = _advance(start, rec.type)


def enumerate_time_periods(
    entry: CalendarEntry, include_skipped: bool = False
) -> Iterator[TimePeriod]:
    heap: List[tuple[datetime, int, Iterator[TimePeriod], TimePeriod]] = []
    for idx, rec in enumerate(entry.recurrences):
        if not isinstance(rec, Recurrence):
            rec = Recurrence.model_validate(rec)
            entry.recurrences[idx] = rec
        gen = _recurrence_generator(entry, rec, idx, include_skipped)
        first = next(gen, None)
        if first:
            heappush(heap, (first.start, idx, gen, first))

    while heap:
        _, idx, gen, period = heappop(heap)
        yield period
        nxt = next(gen, None)
        if nxt:
            heappush(heap, (nxt.start, idx, gen, nxt))


def find_time_period(
    entry: CalendarEntry,
    recurrence_index: int,
    instance_index: int,
    include_skipped: bool = False,
) -> Optional[TimePeriod]:
    for period in enumerate_time_periods(entry, include_skipped=include_skipped):
        if (
            period.recurrence_index == recurrence_index
            and period.instance_index == instance_index
        ):
            return period
    return None


def responsible_for(
    entry: CalendarEntry, recurrence_index: int, instance_index: int
) -> List[str]:
    if 0 <= recurrence_index < len(entry.recurrences):
        rec = entry.recurrences[recurrence_index]
        if not isinstance(rec, Recurrence):
            rec = Recurrence.model_validate(rec)
            entry.recurrences[recurrence_index] = rec
        for d in rec.delegations:
            if not isinstance(d, Delegation):
                d = Delegation.model_validate(d)
            if d.instance_index == instance_index:
                return d.responsible
        if rec.responsible:
            return rec.responsible
    return entry.responsible


def find_delegation(
    entry: CalendarEntry, recurrence_index: int, instance_index: int
) -> Optional[Delegation]:
    if 0 <= recurrence_index < len(entry.recurrences):
        rec = entry.recurrences[recurrence_index]
        if not isinstance(rec, Recurrence):
            rec = Recurrence.model_validate(rec)
            entry.recurrences[recurrence_index] = rec
        for d in rec.delegations:
            if not isinstance(d, Delegation):
                d = Delegation.model_validate(d)
            if d.instance_index == instance_index:
                return d
    return None


def find_instance_note(
    entry: CalendarEntry, recurrence_index: int, instance_index: int
) -> Optional[InstanceNote]:
    if 0 <= recurrence_index < len(entry.recurrences):
        rec = entry.recurrences[recurrence_index]
        if not isinstance(rec, Recurrence):
            rec = Recurrence.model_validate(rec)
            entry.recurrences[recurrence_index] = rec
        for n in rec.notes:
            if not isinstance(n, InstanceNote):
                n = InstanceNote.model_validate(n)
            if n.instance_index == instance_index:
                return n
    return None


def find_instance_duration(
    entry: CalendarEntry, recurrence_index: int, instance_index: int
) -> Optional[InstanceDuration]:
    if 0 <= recurrence_index < len(entry.recurrences):
        rec = entry.recurrences[recurrence_index]
        if not isinstance(rec, Recurrence):
            rec = Recurrence.model_validate(rec)
            entry.recurrences[recurrence_index] = rec
        for d in rec.duration_overrides:
            if not isinstance(d, InstanceDuration):
                d = InstanceDuration.model_validate(d)
            if d.instance_index == instance_index:
                return d
    return None


def duration_for(
    entry: CalendarEntry, recurrence_index: int, instance_index: int
) -> timedelta:
    override = find_instance_duration(entry, recurrence_index, instance_index)
    if override:
        return timedelta(seconds=override.duration_seconds)
    if 0 <= recurrence_index < len(entry.recurrences):
        rec = entry.recurrences[recurrence_index]
        if not isinstance(rec, Recurrence):
            rec = Recurrence.model_validate(rec)
            entry.recurrences[recurrence_index] = rec
        return timedelta(seconds=rec.duration_seconds or 0)
    return timedelta(0)

