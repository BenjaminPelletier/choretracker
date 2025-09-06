import importlib
import sys
from datetime import timedelta
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.append(str(Path(__file__).resolve().parents[1]))

from choretracker.calendar import (
    CalendarEntry,
    CalendarEntryType,
    Recurrence,
    RecurrenceType,
)
from choretracker.time_utils import get_now


def setup_app(tmp_path, monkeypatch):
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("CHORETRACKER_DB", str(db_file))
    if "choretracker.app" in sys.modules:
        del sys.modules["choretracker.app"]
    app_module = importlib.import_module("choretracker.app")
    client = TestClient(app_module.app)
    client.post(
        "/login",
        data={"username": "Admin", "password": "admin"},
        follow_redirects=False,
    )
    return app_module, client


def test_edit_redirects_to_new_entry(tmp_path, monkeypatch):
    app_module, client = setup_app(tmp_path, monkeypatch)
    now = get_now()
    entry = CalendarEntry(
        title="Old",
        description="",
        type=CalendarEntryType.Event,
        recurrences=[
            Recurrence(
                id=0,
                type=RecurrenceType.Weekly,
                first_start=now - timedelta(days=7),
                duration_seconds=60,
            )
        ],
        managers=["Admin"],
    )
    app_module.calendar_store.create(entry)
    original_id = app_module.calendar_store.list_entries()[0].id

    resp = client.post(
        f"/calendar/{original_id}/update",
        json={"title": "New"},
    )
    data = resp.json()
    assert data["status"] == "ok"
    # Should redirect to view the new entry id after splitting
    new_id = int(data["redirect"].rstrip("/").split("/")[-1])
    assert new_id != original_id
    assert app_module.calendar_store.get(new_id).title == "New"
    assert app_module.calendar_store.get(original_id).title == "Old"


def test_no_split_when_no_future_instances(tmp_path, monkeypatch):
    app_module, client = setup_app(tmp_path, monkeypatch)
    now = get_now()
    entry = CalendarEntry(
        title="Past",
        description="",
        type=CalendarEntryType.Event,
        recurrences=[
            Recurrence(
                id=0,
                type=RecurrenceType.OneTime,
                first_start=now - timedelta(days=1),
                duration_seconds=60,
            )
        ],
        managers=["Admin"],
    )
    app_module.calendar_store.create(entry)
    entry_id = app_module.calendar_store.list_entries()[0].id

    resp = client.post(
        f"/calendar/{entry_id}/update",
        json={"title": "Updated"},
    )
    data = resp.json()
    assert data["status"] == "ok"
    assert "redirect" not in data
    assert app_module.calendar_store.get(entry_id).title == "Updated"
