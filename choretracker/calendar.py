from __future__ import annotations

from datetime import datetime, timedelta
from enum import Enum
from dataclasses import dataclass
from heapq import heappush, heappop
import calendar as cal
from typing import Iterator, List, Optional

from sqlmodel import Column, Field, Session, SQLModel, select
from sqlalchemy import JSON


class RecurrenceType(str, Enum):
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


class Recurrence(SQLModel):
    type: RecurrenceType
    offset: Optional[Offset] = None
    skipped_instances: List[int] = Field(default_factory=list)
    responsible: List[str] = Field(default_factory=list)
    delegations: List[Delegation] = Field(default_factory=list)


class CalendarEntry(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str
    description: str = ""
    type: CalendarEntryType
    first_start: datetime
    duration_seconds: int = Field(gt=0)
    recurrences: List[Recurrence] = Field(default_factory=list, sa_column=Column(JSON))
    none_after: Optional[datetime] = None
    responsible: List[str] = Field(default_factory=list, sa_column=Column(JSON))
    managers: List[str] = Field(default_factory=list, sa_column=Column(JSON))

    @property
    def duration(self) -> timedelta:
        return timedelta(seconds=self.duration_seconds)

    @duration.setter
    def duration(self, value: timedelta) -> None:
        self.duration_seconds = int(value.total_seconds())


class CalendarEntryStore:
    def __init__(self, engine):
        self.engine = engine

    def create(self, entry: CalendarEntry) -> None:
        if not entry.managers:
            raise ValueError("CalendarEntry must have at least one manager")
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
            return entry

    def update(self, entry_id: int, new_data: CalendarEntry) -> None:
        if not new_data.managers:
            raise ValueError("CalendarEntry must have at least one manager")
        with Session(self.engine) as session:
            entry = session.get(CalendarEntry, entry_id)
            if not entry:
                return
            entry.title = new_data.title
            entry.description = new_data.description
            entry.first_start = new_data.first_start
            entry.duration_seconds = new_data.duration_seconds
            entry.recurrences = new_data.recurrences
            entry.none_after = new_data.none_after
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
            return entries

    def delete(self, entry_id: int) -> None:
        with Session(self.engine) as session:
            entry = session.get(CalendarEntry, entry_id)
            if entry:
                session.delete(entry)
                session.commit()


class ChoreCompletion(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    entry_id: int = Field(index=True)
    recurrence_index: int
    instance_index: int
    completed_by: str
    completed_at: datetime = Field(default_factory=datetime.now)


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
            return session.exec(stmt).first()

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
            completed_at=completed_at or datetime.now(),
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
            return session.exec(stmt).all()


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


def _advance(start: datetime, rtype: RecurrenceType) -> datetime:
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
    if rec.offset:
        start = _apply_offset(entry.first_start, rec.offset)
    else:
        start = _advance(entry.first_start, rec.type)
    instance = 0
    while start and (not none_after or start <= none_after):
        if include_skipped or instance not in rec.skipped_instances:
            yield TimePeriod(
                start=start,
                end=start + entry.duration,
                recurrence_index=rindex,
                instance_index=instance,
            )
        instance += 1
        start = _advance(start, rec.type)


def enumerate_time_periods(
    entry: CalendarEntry, include_skipped: bool = False
) -> Iterator[TimePeriod]:
    none_after = entry.none_after
    if not none_after or entry.first_start <= none_after:
        yield TimePeriod(
            start=entry.first_start,
            end=entry.first_start + entry.duration,
            recurrence_index=-1,
            instance_index=-1,
        )

    heap: List[tuple[datetime, int, Iterator[TimePeriod], TimePeriod]] = []
    for idx, rec in enumerate(entry.recurrences):
        if not isinstance(rec, Recurrence):
            rec = Recurrence.model_validate(rec)
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
        for d in rec.delegations:
            if not isinstance(d, Delegation):
                d = Delegation.model_validate(d)
            if d.instance_index == instance_index:
                return d
    return None

