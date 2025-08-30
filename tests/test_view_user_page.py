import importlib
import sys
from pathlib import Path
from datetime import timedelta
from choretracker.time_utils import get_now

from fastapi.testclient import TestClient

# Ensure project root is on path
sys.path.append(str(Path(__file__).resolve().parents[1]))

from choretracker.calendar import CalendarEntry, CalendarEntryType, Recurrence, RecurrenceType


def test_view_user_page(tmp_path, monkeypatch):
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("CHORETRACKER_DB", str(db_file))
    if "choretracker.app" in sys.modules:
        del sys.modules["choretracker.app"]
    app_module = importlib.import_module("choretracker.app")

    # create user Bob
    app_module.user_store.create("Bob", "bob", None, set())

    now = get_now()

    # entry where Bob responsible and completion
    entry1 = CalendarEntry(
        title="Dishes",
        description="",
        type=CalendarEntryType.Chore,
        first_start=now - timedelta(days=1),
        duration_seconds=60,
        responsible=["Bob"],
        managers=["Admin"],
    )
    app_module.calendar_store.create(entry1)
    entry1_id = app_module.calendar_store.list_entries()[0].id
    app_module.completion_store.create(entry1_id, -1, -1, "Bob", completed_at=now)

    # entry where Bob responsible via recurrence
    entry2 = CalendarEntry(
        title="Laundry",
        description="",
        type=CalendarEntryType.Chore,
        first_start=now,
        duration_seconds=60,
        recurrences=[Recurrence(type=RecurrenceType.Weekly, responsible=["Bob"])],
        managers=["Admin"],
    )
    app_module.calendar_store.create(entry2)

    # entry managed by Bob
    entry3 = CalendarEntry(
        title="Managed",
        description="",
        type=CalendarEntryType.Event,
        first_start=now,
        duration_seconds=60,
        managers=["Bob"],
    )
    app_module.calendar_store.create(entry3)

    client = TestClient(app_module.app)
    client.post("/login", data={"username": "Bob", "password": "bob"}, follow_redirects=False)

    resp = client.get("/")
    assert "/users/Bob" in resp.text
    assert "/users/Bob/edit" not in resp.text

    resp = client.get("/users/Bob")
    assert "Completions" in resp.text
    assert "Dishes" in resp.text
    assert "Responsible" in resp.text
    assert "Laundry" in resp.text
    assert "Manages" in resp.text
    assert "Managed" in resp.text
