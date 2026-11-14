import importlib
import sys
from pathlib import Path
from datetime import timedelta
from choretracker.time_utils import get_now

from fastapi.testclient import TestClient
from sqlalchemy import event

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
    rec1 = Recurrence(
        id=0,
        type=RecurrenceType.OneTime,
        first_start=now - timedelta(days=1),
        duration_seconds=60,
    )
    entry1 = CalendarEntry(
        title="Dishes",
        description="",
        type=CalendarEntryType.Chore,
        recurrences=[rec1],
        responsible=["Bob"],
        managers=["Admin"],
    )
    app_module.calendar_store.create(entry1)
    entry1_id = app_module.calendar_store.list_entries()[0].id
    app_module.completion_store.create(entry1_id, 0, 0, "Bob", completed_at=now)

    # entry where Bob responsible via recurrence
    rec2 = Recurrence(
        id=0,
        type=RecurrenceType.Weekly,
        first_start=now,
        duration_seconds=60,
        responsible=["Bob"],
    )
    rec2.instance_specifics[3] = app_module.InstanceSpecifics(
        entry_id=0, recurrence_id=0, instance_index=3, note="Special instructions"
    )
    entry2 = CalendarEntry(
        title="Laundry",
        description="",
        type=CalendarEntryType.Chore,
        recurrences=[rec2],
        managers=["Admin"],
    )
    app_module.calendar_store.create(entry2)
    entry2_id = next(e.id for e in app_module.calendar_store.list_entries() if e.title == "Laundry")
    for instance_index in range(20):
        app_module.completion_store.create(entry2_id, 0, instance_index, "Bob", completed_at=now)

    # entry managed by Bob
    rec3 = Recurrence(
        id=0,
        type=RecurrenceType.OneTime,
        first_start=now,
        duration_seconds=60,
    )
    entry3 = CalendarEntry(
        title="Managed",
        description="",
        type=CalendarEntryType.Event,
        recurrences=[rec3],
        managers=["Bob"],
    )
    app_module.calendar_store.create(entry3)

    client = TestClient(app_module.app)
    client.post("/login", data={"username": "Bob", "password": "bob"}, follow_redirects=False)

    resp = client.get("/")
    assert "/users/Bob" in resp.text
    assert "/users/Bob/edit" not in resp.text

    queries = []

    def record_query(conn, cursor, statement, parameters, context, many):
        queries.append(statement.lower())

    event.listen(app_module.engine, "before_cursor_execute", record_query)
    try:
        resp = client.get("/users/Bob")
    finally:
        event.remove(app_module.engine, "before_cursor_execute", record_query)
    assert sum("from calendarentry" in q for q in queries) == 1
    assert sum("from instancespecifics" in q for q in queries) == 1
    assert 'Laundry<span class="note-marker">*</span>' in resp.text
    assert "Completions" in resp.text
    assert "Dishes" in resp.text
    assert "Responsible" in resp.text
    assert "Laundry" in resp.text
    assert "Manages" in resp.text
    assert "Managed" in resp.text
