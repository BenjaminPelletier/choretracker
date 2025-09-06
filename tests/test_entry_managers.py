import importlib
import sys
from pathlib import Path
from datetime import datetime
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


def test_edit_permissions(tmp_path, monkeypatch):
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("CHORETRACKER_DB", str(db_file))
    if "choretracker.app" in sys.modules:
        del sys.modules["choretracker.app"]
    app_module = importlib.import_module("choretracker.app")

    client = TestClient(app_module.app)

    # create additional users
    app_module.user_store.create("Manager", "manager", None, set())
    app_module.user_store.create("Bob", "bob", None, set())

    rec = Recurrence(
        id=0,
        type=RecurrenceType.OneTime,
        first_start=datetime(2000, 1, 1, 0, 0, tzinfo=ZoneInfo("UTC")),
        duration_seconds=60,
    )
    entry = CalendarEntry(
        title="Test",
        description="",
        type=CalendarEntryType.Event,
        recurrences=[rec],
        managers=["Manager"],
    )
    app_module.calendar_store.create(entry)
    entry_id = app_module.calendar_store.list_entries()[0].id

    # Manager cannot edit past entries
    client.post("/login", data={"username": "Manager", "password": "manager"}, follow_redirects=False)
    resp = client.post(f"/calendar/{entry_id}/update", json={"title": "Updated"}, follow_redirects=False)
    assert resp.status_code == 303
    assert app_module.calendar_store.get(entry_id).title == "Test"

    # Non-manager without admin cannot edit
    client.post("/login", data={"username": "Bob", "password": "bob"}, follow_redirects=False)
    resp = client.post(
        f"/calendar/{entry_id}/update", json={"title": "Hack"}, follow_redirects=False
    )
    assert resp.status_code == 303
    assert app_module.calendar_store.get(entry_id).title == "Test"

    # Admin cannot edit past entries
    client.post(
        "/login", data={"username": "Admin", "password": "admin"}, follow_redirects=False
    )
    resp = client.post(
        f"/calendar/{entry_id}/update", json={"title": "AdminUpdate"}, follow_redirects=False
    )
    assert resp.status_code == 303
    assert app_module.calendar_store.get(entry_id).title == "Test"

    # Admin can edit a future entry even if not manager
    future_rec = Recurrence(
        id=1,
        type=RecurrenceType.OneTime,
        first_start=datetime(2100, 1, 1, 0, 0, tzinfo=ZoneInfo("UTC")),
        duration_seconds=60,
    )
    future_entry = CalendarEntry(
        title="Future", description="", type=CalendarEntryType.Event,
        recurrences=[future_rec], managers=["Manager"],
    )
    app_module.calendar_store.create(future_entry)
    future_id = [e.id for e in app_module.calendar_store.list_entries() if e.title == "Future"][0]
    resp = client.post(
        f"/calendar/{future_id}/update", json={"title": "AdminUpdate"}
    )
    assert resp.status_code == 200
    data = resp.json()
    new_id = future_id
    if "redirect" in data:
        new_id = int(data["redirect"].split("/")[-1])
    assert app_module.calendar_store.get(new_id).title == "AdminUpdate"


def test_manager_prepopulated_and_required(tmp_path, monkeypatch):
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("CHORETRACKER_DB", str(db_file))
    if "choretracker.app" in sys.modules:
        del sys.modules["choretracker.app"]
    app_module = importlib.import_module("choretracker.app")

    client = TestClient(app_module.app)

    # Login as admin to access creation form
    client.post("/login", data={"username": "Admin", "password": "admin"}, follow_redirects=False)

    # Form should prepopulate managers with current user
    resp = client.get("/calendar/new/Event")
    assert resp.status_code == 200
    assert "initialManagers.push('Admin')" in resp.text

    # Missing managers should be rejected
    form_data = {
        "title": "Test", "type": "Event", "first_start": "2000-01-01T00:00", "duration_minutes": "1"
    }
    resp = client.post("/calendar/new", data=form_data)
    assert resp.status_code == 400


def test_update_rejects_empty_managers(tmp_path, monkeypatch):
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("CHORETRACKER_DB", str(db_file))
    if "choretracker.app" in sys.modules:
        del sys.modules["choretracker.app"]
    app_module = importlib.import_module("choretracker.app")

    client = TestClient(app_module.app)

    rec = Recurrence(
        id=0,
        type=RecurrenceType.OneTime,
        first_start=datetime.now(ZoneInfo("UTC")),
        duration_seconds=60,
    )
    entry = CalendarEntry(
        title="Test",
        description="",
        type=CalendarEntryType.Event,
        recurrences=[rec],
        managers=["Admin"],
    )
    app_module.calendar_store.create(entry)
    entry_id = app_module.calendar_store.list_entries()[0].id

    client.post("/login", data={"username": "Admin", "password": "admin"}, follow_redirects=False)
    resp = client.post(f"/calendar/{entry_id}/update", json={"managers": []})
    assert resp.status_code == 400
    assert app_module.calendar_store.get(entry_id).managers == ["Admin"]
