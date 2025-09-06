import importlib
import sys
from pathlib import Path
from datetime import datetime, timedelta
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


def test_completed_instance_hidden_after_day(tmp_path, monkeypatch):
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("CHORETRACKER_DB", str(db_file))
    if "choretracker.app" in sys.modules:
        del sys.modules["choretracker.app"]
    app_module = importlib.import_module("choretracker.app")
    import choretracker.calendar as calendar_module

    fake_now = datetime(2000, 1, 1, 10, 0, 0, tzinfo=ZoneInfo("UTC"))
    monkeypatch.setattr(app_module, "get_now", lambda: fake_now)
    monkeypatch.setattr(calendar_module, "get_now", lambda: fake_now)

    client = TestClient(app_module.app)
    client.post(
        "/login",
        data={"username": "Admin", "password": "admin"},
        follow_redirects=False,
    )

    rec = Recurrence(
        id=0,
        type=RecurrenceType.OneTime,
        first_start=fake_now - timedelta(hours=1),
        duration_seconds=48 * 3600,
    )
    entry = CalendarEntry(
        title="Long Chore",
        description="",
        type=CalendarEntryType.Chore,
        recurrences=[rec],
        managers=["Admin"],
        responsible=["Admin"],
    )
    app_module.calendar_store.create(entry)
    entry_id = app_module.calendar_store.list_entries()[0].id

    app_module.completion_store.create(entry_id, 0, 0, "Admin", completed_at=fake_now)

    later_same_day = fake_now + timedelta(hours=1)
    monkeypatch.setattr(app_module, "get_now", lambda: later_same_day)
    monkeypatch.setattr(calendar_module, "get_now", lambda: later_same_day)
    response = client.get("/")
    assert "Long Chore" in response.text

    next_day = fake_now + timedelta(days=1, hours=1)
    monkeypatch.setattr(app_module, "get_now", lambda: next_day)
    monkeypatch.setattr(calendar_module, "get_now", lambda: next_day)
    response = client.get("/")
    assert "Long Chore" not in response.text
