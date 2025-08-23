from __future__ import annotations

from datetime import datetime, timedelta
from enum import Enum
from typing import List, Optional

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


class Recurrence(SQLModel):
    type: RecurrenceType
    offset: Optional[Offset] = None
    skipped_instances: List[int] = Field(default_factory=list)


class CalendarEntry(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str
    description: str = ""
    type: CalendarEntryType
    first_start: datetime
    duration_seconds: int
    recurrences: List[Recurrence] = Field(default_factory=list, sa_column=Column(JSON))
    none_after: Optional[datetime] = None
    responsible: List[str] = Field(default_factory=list, sa_column=Column(JSON))

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
        with Session(self.engine) as session:
            session.add(entry)
            session.commit()

    def list_entries(self) -> List[CalendarEntry]:
        with Session(self.engine) as session:
            return session.exec(select(CalendarEntry)).all()
