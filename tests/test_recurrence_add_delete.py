import importlib
import sys
from datetime import datetime, timedelta
from pathlib import Path
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
    start = datetime.now(ZoneInfo("UTC"))
    entry = CalendarEntry(
        title="AddRec",
        description="",
        type=CalendarEntryType.Chore,
        recurrences=[
            Recurrence(
                id=0,
                type=RecurrenceType.OneTime,
                first_start=start,
                duration_seconds=60,
            )
        ],
        managers=["Admin"],
        responsible=["Admin"],
    )
    app_module.calendar_store.create(entry)
    entry_id = app_module.calendar_store.list_entries()[0].id

    resp = client.post(
        f"/calendar/{entry_id}/recurrence/add",
        json={
            "type": "Weekly",
            "first_start": (start + timedelta(days=1, hours=2, minutes=30)).isoformat(),
            "duration_seconds": 60,
            "responsible": ["Bob"],
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    new_id = entry_id
    if "redirect" in data:
        new_id = int(data["redirect"].split("/")[-1])

    updated = app_module.calendar_store.get(new_id)
    assert len(updated.recurrences) == 2
    assert updated.recurrences[0].type == RecurrenceType.OneTime
    rec = updated.recurrences[1]
    assert rec.type == RecurrenceType.Weekly
    assert rec.first_start == start + timedelta(days=1, hours=2, minutes=30)
    assert rec.responsible == ["Bob"]
def test_delete_recurrence(tmp_path, monkeypatch):
    app_module, client = setup_app(tmp_path, monkeypatch)
    start = datetime.now(ZoneInfo("UTC"))
    entry = CalendarEntry(
        title="DelRec",
        description="",
        type=CalendarEntryType.Chore,
        recurrences=[
            Recurrence(
                id=0,
                type=RecurrenceType.Weekly,
                first_start=start,
                duration_seconds=60,
            ),
            Recurrence(
                id=1,
                type=RecurrenceType.MonthlyDayOfMonth,
                first_start=start,
                duration_seconds=60,
            ),
        ],
        managers=["Admin"],
        responsible=["Admin"],
    )
    app_module.calendar_store.create(entry)
    entry_id = app_module.calendar_store.list_entries()[0].id
    app_module.completion_store.create(entry_id, 1, 0, "Admin")

    resp = client.post(
        f"/calendar/{entry_id}/recurrence/delete",
        json={"recurrence_id": 0},
    )
    assert resp.status_code == 200
    data = resp.json()
    new_id = entry_id
    if "redirect" in data:
        new_id = int(data["redirect"].split("/")[-1])

    updated = app_module.calendar_store.get(new_id)
    assert len(updated.recurrences) == 1
    assert updated.recurrences[0].type == RecurrenceType.MonthlyDayOfMonth

    comps = app_module.completion_store.list_for_entry(new_id)
    assert len(comps) == 1
    assert comps[0].recurrence_id == 1
