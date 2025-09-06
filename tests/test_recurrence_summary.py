import importlib
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

# Ensure project root on path
sys.path.append(str(Path(__file__).resolve().parents[1]))

from choretracker.calendar import (
    CalendarEntry,
    CalendarEntryType,
    Recurrence,
    RecurrenceType,
)


def _setup_app(tmp_path, monkeypatch):
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("CHORETRACKER_DB", str(db_file))
    if "choretracker.app" in sys.modules:
        del sys.modules["choretracker.app"]
    app_module = importlib.import_module("choretracker.app")
    client = TestClient(app_module.app)
    client.post(
        "/login",
        data={"username": "Admin", "password": "admin"},
        follow_redirects=False,
    )
    return app_module, client


def test_recurrence_summary_display(tmp_path, monkeypatch):
    app_module, client = _setup_app(tmp_path, monkeypatch)
    tz = ZoneInfo("UTC")
    entry = CalendarEntry(
        title="RecSum",
        description="",
        type=CalendarEntryType.Event,
        recurrences=[
            Recurrence(
                id=0,
                type=RecurrenceType.OneTime,
                first_start=datetime(2025, 8, 31, 18, 0, tzinfo=tz),
                duration_seconds=15 * 3600,
            ),
            Recurrence(
                id=1,
                type=RecurrenceType.Weekly,
                first_start=datetime(2025, 2, 4, 14, 0, tzinfo=tz),
                duration_seconds=2 * 3600,
            ),
            Recurrence(
                id=2,
                type=RecurrenceType.MonthlyDayOfMonth,
                first_start=datetime(2025, 1, 5, 7, 0, tzinfo=tz),
                duration_seconds=6 * 3600,
            ),
            Recurrence(
                id=3,
                type=RecurrenceType.MonthlyDayOfWeek,
                first_start=datetime(2025, 1, 11, 10, 0, tzinfo=tz),
                duration_seconds=1 * 3600,
            ),
            Recurrence(
                id=4,
                type=RecurrenceType.AnnualDayOfMonth,
                first_start=datetime(2025, 7, 4, 15, 0, tzinfo=tz),
                duration_seconds=6 * 3600,
            ),
        ],
        managers=["Admin"],
    )
    app_module.calendar_store.create(entry)
    entry_id = app_module.calendar_store.list_entries()[0].id
    page = client.get(f"/calendar/entry/{entry_id}")
    assert "OneTime, Sun 2025-08-31 18:00 to Mon 09-01 09:00" in page.text
    assert "Weekly, Tue 14:00-16:00" in page.text
    assert "MonthlyDayOfMonth, 5th 07:00-13:00" in page.text
    assert "MonthlyDayOfWeek, second Sat 10:00-11:00" in page.text
    assert "AnnualDayOfMonth, July 4 15:00-21:00" in page.text

