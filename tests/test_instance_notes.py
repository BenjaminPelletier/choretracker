import sys
import importlib
from pathlib import Path
from datetime import timedelta
from choretracker.time_utils import get_now

from fastapi.testclient import TestClient

# Ensure project root on path
sys.path.append(str(Path(__file__).resolve().parents[1]))

from choretracker.calendar import (
    CalendarEntry,
    CalendarEntryType,
    Recurrence,
    RecurrenceType,
)


def test_instance_notes(tmp_path, monkeypatch):
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("CHORETRACKER_DB", str(db_file))
    if "choretracker.app" in sys.modules:
        del sys.modules["choretracker.app"]
    app_module = importlib.import_module("choretracker.app")
    client = TestClient(app_module.app)

    client.post("/login", data={"username": "Admin", "password": "admin"}, follow_redirects=False)

    start = get_now() + timedelta(minutes=5)
    entry = CalendarEntry(
        title="Laundry",
        description="",
        type=CalendarEntryType.Chore,
        first_start=start,
        duration_seconds=60,
        recurrences=[Recurrence(type=RecurrenceType.Weekly)],
        responsible=["Admin"],
        managers=["Admin"],
    )
    app_module.calendar_store.create(entry)
    entry_id = app_module.calendar_store.list_entries()[0].id

    resp = client.post(
        f"/calendar/{entry_id}/note",
        data={"recurrence_index": 0, "instance_index": 0, "note": "<script>alert(1)</script>**Bold**"},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    page = client.get(f"/calendar/entry/{entry_id}/period/0/0")
    assert "<script>alert(1)</script>" not in page.text
    assert "<strong>Bold</strong>" in page.text

    home = client.get("/")
    assert '<span class="note-marker">*</span>' in home.text

    resp = client.post(
        f"/calendar/{entry_id}/note/remove",
        data={"recurrence_index": 0, "instance_index": 0},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    home = client.get("/")
    assert '<span class="note-marker">*</span>' not in home.text
