import importlib
import sys
from pathlib import Path
from datetime import datetime

from fastapi.testclient import TestClient

# Ensure project root on path
sys.path.append(str(Path(__file__).resolve().parents[1]))

from choretracker.calendar import CalendarEntry, CalendarEntryType


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

    entry = CalendarEntry(
        title="Test",
        description="",
        type=CalendarEntryType.Event,
        first_start=datetime(2000, 1, 1, 0, 0),
        duration_seconds=60,
        managers=["Manager"],
    )
    app_module.calendar_store.create(entry)
    entry_id = app_module.calendar_store.list_entries()[0].id

    # Manager can edit
    client.post("/login", data={"username": "Manager", "password": "manager"}, follow_redirects=False)
    resp = client.post(f"/calendar/{entry_id}/update", json={"title": "Updated"})
    assert resp.status_code == 200
    assert app_module.calendar_store.get(entry_id).title == "Updated"

    # Non-manager without admin cannot edit
    client.post("/login", data={"username": "Bob", "password": "bob"}, follow_redirects=False)
    resp = client.post(f"/calendar/{entry_id}/update", json={"title": "Hack"}, follow_redirects=False)
    assert resp.status_code == 303
    assert app_module.calendar_store.get(entry_id).title == "Updated"

    # Admin can edit even if not manager
    client.post("/login", data={"username": "Admin", "password": "admin"}, follow_redirects=False)
    resp = client.post(f"/calendar/{entry_id}/update", json={"title": "AdminUpdate"})
    assert resp.status_code == 200
    assert app_module.calendar_store.get(entry_id).title == "AdminUpdate"


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
    assert "entryManagersManager.addUser('Admin')" in resp.text

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

    entry = CalendarEntry(
        title="Test",
        description="",
        type=CalendarEntryType.Event,
        first_start=datetime(2000, 1, 1, 0, 0),
        duration_seconds=60,
        managers=["Admin"],
    )
    app_module.calendar_store.create(entry)
    entry_id = app_module.calendar_store.list_entries()[0].id

    client.post("/login", data={"username": "Admin", "password": "admin"}, follow_redirects=False)
    resp = client.post(f"/calendar/{entry_id}/update", json={"managers": []})
    assert resp.status_code == 400
    assert app_module.calendar_store.get(entry_id).managers == ["Admin"]
