import importlib
import sys
from datetime import timedelta
from choretracker.time_utils import get_now
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.append(str(Path(__file__).resolve().parents[1]))

from choretracker.calendar import (
    CalendarEntry,
    CalendarEntryType,
    InstanceSpecifics,
    Recurrence,
    RecurrenceType,
)


def test_username_change_updates_references(tmp_path, monkeypatch):
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("CHORETRACKER_DB", str(db_file))
    if "choretracker.app" in sys.modules:
        del sys.modules["choretracker.app"]
    app_module = importlib.import_module("choretracker.app")

    app_module.user_store.create("Bob", "bob", None, set())
    entry = CalendarEntry(
        title="Test",
        description="",
        type=CalendarEntryType.Chore,
        first_start=get_now() + timedelta(days=1),
        duration_seconds=60,
        responsible=["Bob"],
        managers=["Bob"],
        recurrences=[
            Recurrence(
                id=0,
                type=RecurrenceType.Weekly,
                responsible=["Bob"],
            )
        ],
    )
    entry.recurrences[0].instance_specifics[0] = InstanceSpecifics(
        entry_id=0, recurrence_id=0, instance_index=0, responsible=["Bob"]
    )
    app_module.calendar_store.create(entry)
    entry_id = app_module.calendar_store.list_entries()[0].id
    app_module.completion_store.create(entry_id, -1, -1, "Bob")

    client = TestClient(app_module.app)
    client.post(
        "/login",
        data={"username": "Admin", "password": "admin"},
        follow_redirects=False,
    )

    resp = client.post(
        "/users/Bob/edit",
        data={"username": "Bobby"},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    assert app_module.user_store.get("Bob") is None
    assert app_module.user_store.get("Bobby") is not None

    entry = app_module.calendar_store.list_entries()[0]
    assert entry.managers == ["Bobby"]
    assert entry.responsible == ["Bobby"]
    assert entry.recurrences[0].responsible == ["Bobby"]
    assert entry.recurrences[0].instance_specifics[0].responsible == ["Bobby"]

    comp = app_module.completion_store.list_for_entry(entry_id)[0]
    assert comp.completed_by == "Bobby"

