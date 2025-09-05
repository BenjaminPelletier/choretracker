import importlib
import sys
from pathlib import Path
from datetime import timedelta
from choretracker.time_utils import get_now

from fastapi.testclient import TestClient

sys.path.append(str(Path(__file__).resolve().parents[1]))


def test_non_admin_cannot_create_or_edit_past_entries(tmp_path, monkeypatch):
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("CHORETRACKER_DB", str(db_file))
    if "choretracker.app" in sys.modules:
        del sys.modules["choretracker.app"]
    app_module = importlib.import_module("choretracker.app")

    app_module.user_store.create("User", "user", None, {"events.write"})

    client = TestClient(app_module.app)
    client.post("/login", data={"username": "User", "password": "user"}, follow_redirects=False)

    past = (get_now() - timedelta(days=1)).isoformat()
    resp = client.post(
        "/calendar/new",
        data={
            "title": "Past",
            "type": "Event",
            "first_start": past,
            "duration_hours": "1",
            "recurrence_type[]": "OneTime",
            "managers": "User",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 400
    assert app_module.calendar_store.list_entries() == []

    future = (get_now() + timedelta(days=1)).isoformat(timespec="minutes")
    resp = client.post(
        "/calendar/new",
        data={
            "title": "Future",
            "type": "Event",
            "first_start": future,
            "duration_hours": "1",
            "recurrence_type[]": "OneTime",
            "managers": "User",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    entry_id = app_module.calendar_store.list_entries()[0].id

    past2 = (get_now() - timedelta(days=2)).isoformat()
    resp = client.post(
        f"/calendar/{entry_id}/recurrence/update",
        json={"recurrence_id": 0, "first_start": past2},
        follow_redirects=False,
    )
    assert resp.status_code == 400
    stored = app_module.calendar_store.get(entry_id)
    assert stored.recurrences[0].first_start.isoformat(timespec="minutes") == future
