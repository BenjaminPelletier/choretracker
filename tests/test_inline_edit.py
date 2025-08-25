import importlib
import sys
from pathlib import Path
from datetime import datetime

from fastapi.testclient import TestClient

# Ensure project root on path
sys.path.append(str(Path(__file__).resolve().parents[1]))

from choretracker.calendar import CalendarEntry, CalendarEntryType


def test_inline_update(tmp_path, monkeypatch):
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("CHORETRACKER_DB", str(db_file))
    if "choretracker.app" in sys.modules:
        del sys.modules["choretracker.app"]
    app_module = importlib.import_module("choretracker.app")

    client = TestClient(app_module.app)
    client.post("/login", data={"username": "Admin", "password": "admin"}, follow_redirects=False)

    entry = CalendarEntry(
        title="Old",
        description="Old desc",
        type=CalendarEntryType.Event,
        first_start=datetime(2000, 1, 1, 0, 0),
        duration_seconds=60,
    )
    app_module.calendar_store.create(entry)
    entry_id = app_module.calendar_store.list_entries()[0].id

    # Update first_start and description
    client.post(f"/calendar/{entry_id}/update", json={"first_start": "2000-02-01T00:00", "description": "New desc"})
    page = client.get(f"/calendar/entry/{entry_id}")
    assert "2000-02-01 00:00" in page.text
    assert "New desc" in page.text

    # Update title and type
    client.post(f"/calendar/{entry_id}/update", json={"title": "New Title", "type": "Reminder"})
    page = client.get(f"/calendar/entry/{entry_id}")
    assert "New Title" in page.text
    assert "Reminder" in page.text
