import importlib
import sys
from pathlib import Path
from datetime import datetime

from fastapi.testclient import TestClient

# Ensure project root on path
sys.path.append(str(Path(__file__).resolve().parents[1]))

from choretracker.calendar import (
    CalendarEntry,
    CalendarEntryType,
    Recurrence,
    RecurrenceType,
)


def test_completed_by_username_shown(tmp_path, monkeypatch):
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("CHORETRACKER_DB", str(db_file))
    if "choretracker.app" in sys.modules:
        del sys.modules["choretracker.app"]
    app_module = importlib.import_module("choretracker.app")
    client = TestClient(app_module.app)

    # login as Admin user
    client.post("/login", data={"username": "Admin", "password": "admin"}, follow_redirects=False)

    entry = CalendarEntry(
        title="Dishes",
        description="",
        type=CalendarEntryType.Chore,
        first_start=datetime(2000, 1, 1, 8, 0, 0),
        duration_seconds=60,
        recurrences=[Recurrence(type=RecurrenceType.Weekly)],
    )
    app_module.calendar_store.create(entry)
    entry_id = app_module.calendar_store.list_entries()[0].id

    # mark completion for first recurrence instance
    app_module.completion_store.create(entry_id, 0, 0, "Admin")

    response = client.get(f"/calendar/entry/{entry_id}/period/0/0")
    assert '<span class="completed-by">by Admin</span>' in response.text
