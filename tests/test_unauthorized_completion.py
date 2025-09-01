import importlib
import sys
from pathlib import Path

from fastapi.testclient import TestClient

# Ensure project root on path
sys.path.append(str(Path(__file__).resolve().parents[1]))

from choretracker.calendar import CalendarEntry, CalendarEntryType
from choretracker.time_utils import get_now

def test_unauthorized_completion_flashes_message(tmp_path, monkeypatch):
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("CHORETRACKER_DB", str(db_file))
    if "choretracker.app" in sys.modules:
        del sys.modules["choretracker.app"]
    app_module = importlib.import_module("choretracker.app")

    # create user without completion permissions
    app_module.user_store.create("Bob", "bob", None, set())

    now = get_now()
    entry = CalendarEntry(
        title="Dishes",
        description="",
        type=CalendarEntryType.Chore,
        first_start=now,
        duration_seconds=60,
        managers=["Admin"],
    )
    app_module.calendar_store.create(entry)
    entry_id = app_module.calendar_store.list_entries()[0].id

    client = TestClient(app_module.app)
    client.post("/login", data={"username": "Bob", "password": "bob"}, follow_redirects=False)

    # home page shows empty checkbox even without permission
    resp = client.get("/")
    assert f'data-entry="{entry_id}"' in resp.text
    assert "checkbox-empty.svg" in resp.text

    # attempt to complete chore without permission
    resp = client.post(
        f"/calendar/{entry_id}/completion",
        json={"recurrence_index": -1, "instance_index": -1},
    )
    assert resp.status_code == 403
    assert (
        resp.json()["message"]
        == "Bob isn't authorized to complete this instance"
    )

