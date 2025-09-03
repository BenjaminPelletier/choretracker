import sys
import importlib
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# Ensure project root on path
sys.path.append(str(Path(__file__).resolve().parents[1]))

from choretracker.calendar import (
    CalendarEntry,
    CalendarEntryType,
    Recurrence,
    RecurrenceType,
    enumerate_time_periods,
)
from itertools import islice


def test_recurrence_first_start_duration(tmp_path, monkeypatch):
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("CHORETRACKER_DB", str(db_file))
    if "choretracker.app" in sys.modules:
        del sys.modules["choretracker.app"]
    app_module = importlib.import_module("choretracker.app")

    start = datetime(2000, 1, 1, 0, 0, tzinfo=ZoneInfo("UTC"))
    rec_start = datetime(2000, 1, 8, 0, 0, tzinfo=ZoneInfo("UTC"))

    entry = CalendarEntry(
        title="Task",
        description="",
        type=CalendarEntryType.Chore,
        first_start=start,
        duration_seconds=3600,
        recurrences=[
            Recurrence(
                type=RecurrenceType.Weekly,
                first_start=rec_start,
                duration_seconds=600,
            )
        ],
        responsible=["Admin"],
        managers=["Admin"],
    )
    app_module.calendar_store.create(entry)
    entry_id = app_module.calendar_store.list_entries()[0].id
    entry = app_module.calendar_store.get(entry_id)

    periods = list(islice(enumerate_time_periods(entry), 2))
    assert periods[0].start == start
    assert periods[0].end - periods[0].start == timedelta(seconds=3600)
    assert periods[1].start == rec_start
    assert periods[1].end - periods[1].start == timedelta(seconds=600)
