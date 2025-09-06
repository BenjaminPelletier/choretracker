import importlib
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

sys.path.append(str(Path(__file__).resolve().parents[1]))


def _setup_app(tmp_path, monkeypatch, fake_now):
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("CHORETRACKER_DB", str(db_file))
    if "choretracker.app" in sys.modules:
        del sys.modules["choretracker.app"]
    app_module = importlib.import_module("choretracker.app")
    monkeypatch.setattr(app_module, "get_now", lambda: fake_now)
    import choretracker.calendar as calendar_module
    monkeypatch.setattr(calendar_module, "get_now", lambda: fake_now)
    client = TestClient(app_module.app)
    client.post(
        "/login",
        data={"username": "Admin", "password": "admin"},
        follow_redirects=False,
    )
    return app_module, calendar_module, client


def test_edit_entry_with_past_instance_specifics(tmp_path, monkeypatch):
    fake_now = datetime(2000, 1, 8, 12, 0, tzinfo=ZoneInfo("UTC"))
    app_module, calendar_module, client = _setup_app(tmp_path, monkeypatch, fake_now)

    rec = calendar_module.Recurrence(
        id=0,
        type=calendar_module.RecurrenceType.Weekly,
        first_start=fake_now - timedelta(days=7),
        duration_seconds=60,
    )
    rec.instance_specifics[0] = calendar_module.InstanceSpecifics(
        entry_id=0,
        recurrence_id=0,
        instance_index=0,
        note="past",
    )
    entry = calendar_module.CalendarEntry(
        title="Old",
        description="",
        type=calendar_module.CalendarEntryType.Chore,
        recurrences=[rec],
        managers=["Admin"],
        responsible=["Admin"],
    )
    app_module.calendar_store.create(entry)
    original_id = app_module.calendar_store.list_entries()[0].id

    app_module.completion_store.create(original_id, 0, 0, "Admin")

    resp = client.post(
        f"/calendar/{original_id}/update", json={"title": "New"}
    )
    data = resp.json()
    assert data["status"] == "ok"
    assert "redirect" in data
    new_id = int(data["redirect"].split("/")[-1])
    assert new_id != original_id
    assert app_module.calendar_store.get(new_id).title == "New"

