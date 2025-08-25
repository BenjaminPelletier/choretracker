from pathlib import Path
from datetime import datetime
import importlib
import sys

from fastapi.testclient import TestClient

# Ensure project root on path
sys.path.append(str(Path(__file__).resolve().parents[1]))

from choretracker.calendar import CalendarEntry, CalendarEntryType, Recurrence, RecurrenceType


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


def test_add_recurrence(tmp_path, monkeypatch):
    app_module, client = setup_app(tmp_path, monkeypatch)
    entry = CalendarEntry(
        title="AddRec",
        description="",
        type=CalendarEntryType.Chore,
        first_start=datetime(2000, 1, 1, 0, 0),
        duration_seconds=60,
        recurrences=[],
    )
    app_module.calendar_store.create(entry)
    entry_id = app_module.calendar_store.list_entries()[0].id

    resp = client.post(
        f"/calendar/{entry_id}/recurrence/add",
        json={
            "type": "Weekly",
            "offset_days": 1,
            "offset_hours": 2,
            "offset_minutes": 30,
            "responsible": ["Bob"],
        },
    )
    assert resp.status_code == 200

    updated = app_module.calendar_store.get(entry_id)
    assert len(updated.recurrences) == 1
    rec = updated.recurrences[0]
    assert rec.type == RecurrenceType.Weekly
    assert rec.offset and rec.offset.exact_duration_seconds == 1 * 86400 + 2 * 3600 + 30 * 60
    assert rec.responsible == ["Bob"]


def test_delete_recurrence(tmp_path, monkeypatch):
    app_module, client = setup_app(tmp_path, monkeypatch)
    entry = CalendarEntry(
        title="DelRec",
        description="",
        type=CalendarEntryType.Chore,
        first_start=datetime(2000, 1, 1, 0, 0),
        duration_seconds=60,
        recurrences=[
            Recurrence(type=RecurrenceType.Weekly),
            Recurrence(type=RecurrenceType.MonthlyDayOfMonth),
        ],
    )
    app_module.calendar_store.create(entry)
    entry_id = app_module.calendar_store.list_entries()[0].id
    app_module.completion_store.create(entry_id, 1, 0, "Admin")

    resp = client.post(
        f"/calendar/{entry_id}/recurrence/delete",
        json={"recurrence_index": 0},
    )
    assert resp.status_code == 200

    updated = app_module.calendar_store.get(entry_id)
    assert len(updated.recurrences) == 1
    assert updated.recurrences[0].type == RecurrenceType.MonthlyDayOfMonth

    comps = app_module.completion_store.list_for_entry(entry_id)
    assert len(comps) == 1
    assert comps[0].recurrence_index == 0
