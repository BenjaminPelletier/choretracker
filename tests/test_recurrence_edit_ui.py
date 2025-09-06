import sys
import importlib
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
    client.post("/login", data={"username": "Admin", "password": "admin"}, follow_redirects=False)
    return app_module, client


def test_recurrence_edit_includes_first_start_and_duration(tmp_path, monkeypatch):
    app_module, client = _setup_app(tmp_path, monkeypatch)
    start = datetime(2000, 1, 1, 0, 0, tzinfo=ZoneInfo("UTC"))
    entry = CalendarEntry(
        title="RecEdit",
        description="",
        type=CalendarEntryType.Event,
        recurrences=[
            Recurrence(
                id=0,
                type=RecurrenceType.OneTime,
                first_start=start,
                duration_seconds=60,
            )
        ],
        managers=["Admin"],
    )
    app_module.calendar_store.create(entry)
    entry_id = app_module.calendar_store.list_entries()[0].id
    page = client.get(f"/calendar/entry/{entry_id}")
    assert 'data-first-start="2000-01-01T00:00"' in page.text
    assert 'data-duration-seconds="60"' in page.text

