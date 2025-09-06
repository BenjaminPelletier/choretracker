import sys
import importlib
from pathlib import Path
from datetime import timedelta

from choretracker.time_utils import get_now
from fastapi.testclient import TestClient

# Ensure project root on path
sys.path.append(str(Path(__file__).resolve().parents[1]))

from choretracker.calendar import (
    CalendarEntry,
    CalendarEntryType,
    Recurrence,
    RecurrenceType,
    enumerate_time_periods,
)


def test_instance_start_override(tmp_path, monkeypatch):
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("CHORETRACKER_DB", str(db_file))
    if "choretracker.app" in sys.modules:
        del sys.modules["choretracker.app"]
    app_module = importlib.import_module("choretracker.app")
    client = TestClient(app_module.app)

    client.post("/login", data={"username": "Admin", "password": "admin"}, follow_redirects=False)

    start = get_now() + timedelta(hours=1)
    rec = Recurrence(
        id=0,
        type=RecurrenceType.OneTime,
        first_start=start,
        duration_seconds=3600,
    )
    entry = CalendarEntry(
        title="Task",
        description="",
        type=CalendarEntryType.Event,
        recurrences=[rec],
        responsible=["Admin"],
        managers=["Admin"],
    )
    app_module.calendar_store.create(entry)
    entry_id = app_module.calendar_store.list_entries()[0].id

    new_start = (start + timedelta(hours=2)).replace(second=0, microsecond=0)
    resp = client.post(
        f"/calendar/{entry_id}/start",
        data={
            "recurrence_id": 0,
            "instance_index": 0,
            "start_time": new_start.strftime("%Y-%m-%dT%H:%M"),
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303

    entry = app_module.calendar_store.get(entry_id)
    period = next(enumerate_time_periods(entry))
    assert period.start == new_start

    resp = client.post(
        f"/calendar/{entry_id}/start/remove",
        data={
            "recurrence_id": 0,
            "instance_index": 0,
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303

    entry = app_module.calendar_store.get(entry_id)
    period = next(enumerate_time_periods(entry))
    assert period.start == start


def test_start_override_order_enforced(tmp_path, monkeypatch):
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("CHORETRACKER_DB", str(db_file))
    if "choretracker.app" in sys.modules:
        del sys.modules["choretracker.app"]
    app_module = importlib.import_module("choretracker.app")
    client = TestClient(app_module.app)

    client.post("/login", data={"username": "Admin", "password": "admin"}, follow_redirects=False)

    start = get_now() + timedelta(days=1)
    rec = Recurrence(
        id=0,
        type=RecurrenceType.Weekly,
        first_start=start,
        duration_seconds=3600,
    )
    entry = CalendarEntry(
        title="Task",
        description="",
        type=CalendarEntryType.Event,
        recurrences=[rec],
        responsible=["Admin"],
        managers=["Admin"],
    )
    app_module.calendar_store.create(entry)
    entry_id = app_module.calendar_store.list_entries()[0].id

    earlier = (start - timedelta(hours=1)).replace(second=0, microsecond=0)
    resp = client.post(
        f"/calendar/{entry_id}/start",
        data={
            "recurrence_id": 0,
            "instance_index": 1,
            "start_time": earlier.strftime("%Y-%m-%dT%H:%M"),
        },
        follow_redirects=False,
    )
    assert resp.status_code == 400
    assert "previous instance's start" in resp.text

    later = (start + timedelta(days=8)).replace(second=0, microsecond=0)
    resp = client.post(
        f"/calendar/{entry_id}/start",
        data={
            "recurrence_id": 0,
            "instance_index": 0,
            "start_time": later.strftime("%Y-%m-%dT%H:%M"),
        },
        follow_redirects=False,
    )
    assert resp.status_code == 400
    assert "next instance's start" in resp.text


def test_start_override_respects_other_recurrences(tmp_path, monkeypatch):
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("CHORETRACKER_DB", str(db_file))
    if "choretracker.app" in sys.modules:
        del sys.modules["choretracker.app"]
    app_module = importlib.import_module("choretracker.app")
    client = TestClient(app_module.app)

    client.post("/login", data={"username": "Admin", "password": "admin"}, follow_redirects=False)

    start = get_now() + timedelta(days=1)
    rec0 = Recurrence(
        id=0,
        type=RecurrenceType.OneTime,
        first_start=start,
        duration_seconds=3600,
    )
    rec1 = Recurrence(
        id=1,
        type=RecurrenceType.OneTime,
        first_start=start + timedelta(hours=2),
        duration_seconds=3600,
    )
    entry = CalendarEntry(
        title="Task",
        description="",
        type=CalendarEntryType.Event,
        recurrences=[rec0, rec1],
        responsible=["Admin"],
        managers=["Admin"],
    )
    app_module.calendar_store.create(entry)
    entry_id = app_module.calendar_store.list_entries()[0].id

    new_start = (start - timedelta(hours=1)).replace(second=0, microsecond=0)
    resp = client.post(
        f"/calendar/{entry_id}/start",
        data={
            "recurrence_id": 1,
            "instance_index": 0,
            "start_time": new_start.strftime("%Y-%m-%dT%H:%M"),
        },
        follow_redirects=False,
    )
    assert resp.status_code == 400
    assert "previous instance's start" in resp.text
