import importlib
import sys
from pathlib import Path
from datetime import timedelta
from choretracker.time_utils import get_now

from fastapi.testclient import TestClient

sys.path.append(str(Path(__file__).resolve().parents[1]))

from choretracker.calendar import CalendarEntry, CalendarEntryType


def test_user_deletion_restricted(tmp_path, monkeypatch):
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
    )
    app_module.calendar_store.create(entry)
    entry_id = app_module.calendar_store.list_entries()[0].id
    app_module.completion_store.create(entry_id, -1, -1, "Bob")

    client = TestClient(app_module.app)
    client.post("/login", data={"username": "Admin", "password": "admin"}, follow_redirects=False)

    resp = client.get("/users")
    assert f"/users/Bob/delete" not in resp.text

    resp = client.post("/users/Bob/delete", follow_redirects=False)
    assert resp.status_code == 303
    assert app_module.user_store.get("Bob") is not None
