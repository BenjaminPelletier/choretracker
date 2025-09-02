import importlib
import sys
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

sys.path.append(str(Path(__file__).resolve().parents[1]))

from choretracker.calendar import CalendarEntry, CalendarEntryType, Recurrence, RecurrenceType


def _setup_app(tmp_path, monkeypatch, fake_now):
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("CHORETRACKER_DB", str(db_file))
    if "choretracker.app" in sys.modules:
        del sys.modules["choretracker.app"]
    app_module = importlib.import_module("choretracker.app")
    monkeypatch.setattr(app_module, "get_now", lambda: fake_now)
    import choretracker.calendar as calendar_module
    monkeypatch.setattr(calendar_module, "get_now", lambda: fake_now)
    client = TestClient(app_module.app)
    client.post("/login", data={"username": "Admin", "password": "admin"}, follow_redirects=False)
    return app_module, client


def test_no_upcoming_for_past_recurring_with_completion(tmp_path, monkeypatch):
    fake_now = datetime(2025, 9, 2, 5, 12, 47, tzinfo=ZoneInfo("UTC"))
    app_module, client = _setup_app(tmp_path, monkeypatch, fake_now)

    rec1 = Recurrence(
        type=RecurrenceType.OneTime,
        first_start=fake_now - timedelta(days=3),
        duration_seconds=5 * 24 * 60 * 60,
    )
    rec2 = Recurrence(
        type=RecurrenceType.OneTime,
        first_start=fake_now - timedelta(days=2),
        duration_seconds=24 * 60 * 60,
    )
    entry = CalendarEntry(
        title="Overlap",
        description="",
        type=CalendarEntryType.Chore,
        recurrences=[rec1, rec2],
        managers=["Admin"],
    )
    app_module.calendar_store.create(entry)
    entry_id = app_module.calendar_store.list_entries()[0].id
    app_module.completion_store.create(entry_id, 1, 0, "Admin")

    response = client.get("/")
    text = response.text
    assert '<span class="time-suffix" data-kind="starts-in"' not in text
