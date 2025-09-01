import importlib
import sys
from pathlib import Path
from datetime import timedelta
from choretracker.time_utils import get_now

from fastapi.testclient import TestClient

# Ensure project root on path
sys.path.append(str(Path(__file__).resolve().parents[1]))

from choretracker.calendar import CalendarEntry, CalendarEntryType
import re


def test_due_not_shown_when_completed(tmp_path, monkeypatch):
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("CHORETRACKER_DB", str(db_file))
    if "choretracker.app" in sys.modules:
        del sys.modules["choretracker.app"]
    app_module = importlib.import_module("choretracker.app")
    client = TestClient(app_module.app)

    # login as Admin user
    client.post("/login", data={"username": "Admin", "password": "admin"}, follow_redirects=False)

    now = get_now()
    entry = CalendarEntry(
        title="Laundry",
        description="",
        type=CalendarEntryType.Chore,
        first_start=now - timedelta(minutes=5),
        duration_seconds=3600,
        managers=["Admin"],
    )
    app_module.calendar_store.create(entry)
    entry_id = app_module.calendar_store.list_entries()[0].id

    # mark completion for the period
    app_module.completion_store.create(entry_id, 0, 0, "Admin")

    response = client.get("/")
    assert "Laundry" in response.text
    assert re.search(r'<span[^>]*data-kind="due-in"', response.text) is None
