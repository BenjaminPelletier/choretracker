import importlib
import sys
from pathlib import Path
from datetime import datetime

from fastapi.testclient import TestClient

# Ensure project root on path
sys.path.append(str(Path(__file__).resolve().parents[1]))

from choretracker.calendar import CalendarEntry, CalendarEntryType, Recurrence, RecurrenceType, responsible_for


def test_delegate_first_instance(tmp_path, monkeypatch):
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("CHORETRACKER_DB", str(db_file))
    if "choretracker.app" in sys.modules:
        del sys.modules["choretracker.app"]
    app_module = importlib.import_module("choretracker.app")
    client = TestClient(app_module.app)

    client.post("/login", data={"username": "Admin", "password": "admin"}, follow_redirects=False)
    app_module.user_store.create("Bob", "pw", None, set())

    entry = CalendarEntry(
        title="Laundry",
        description="",
        type=CalendarEntryType.Chore,
        first_start=datetime(2000, 1, 1, 8, 0, 0),
        duration_seconds=60,
        recurrences=[Recurrence(type=RecurrenceType.Weekly)],
        responsible=["Admin"],
        managers=["Admin"],
    )
    app_module.calendar_store.create(entry)
    entry_id = app_module.calendar_store.list_entries()[0].id

    resp = client.post(
        f"/calendar/{entry_id}/delegation",
        data={"recurrence_index": -1, "instance_index": -1, "responsible[]": "Bob"},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    entry = app_module.calendar_store.get(entry_id)
    assert entry.first_instance_delegates == ["Bob"]
    assert responsible_for(entry, -1, -1) == ["Bob"]

    page = client.get(f"/calendar/entry/{entry_id}/period/-1/-1")
    assert "Remove delegation" in page.text

    resp = client.post(
        f"/calendar/{entry_id}/delegation/remove",
        data={"recurrence_index": -1, "instance_index": -1},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    entry = app_module.calendar_store.get(entry_id)
    assert entry.first_instance_delegates == []
    page = client.get(f"/calendar/entry/{entry_id}/period/-1/-1")
    assert "Delegate this instance" in page.text

    resp = client.post(
        f"/calendar/{entry_id}/delegation",
        data={"recurrence_index": -1, "instance_index": -1, "responsible[]": "Bob"},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    resp = client.post(
        f"/calendar/{entry_id}/skip",
        data={"recurrence_index": -1, "instance_index": -1},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    entry = app_module.calendar_store.get(entry_id)
    assert entry.first_instance_delegates == []
    assert entry.skip_first_instance is True
    page = client.get(f"/calendar/entry/{entry_id}/period/-1/-1")
    assert "<h2>Delegation</h2>" not in page.text

    client.post(
        f"/calendar/{entry_id}/skip/remove",
        data={"recurrence_index": -1, "instance_index": -1},
        follow_redirects=False,
    )
    page = client.get(f"/calendar/entry/{entry_id}/period/-1/-1")
    assert "Delegate this instance" in page.text
