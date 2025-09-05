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


def test_instance_duration_override(tmp_path, monkeypatch):
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("CHORETRACKER_DB", str(db_file))
    if "choretracker.app" in sys.modules:
        del sys.modules["choretracker.app"]
    app_module = importlib.import_module("choretracker.app")
    client = TestClient(app_module.app)

    client.post("/login", data={"username": "Admin", "password": "admin"}, follow_redirects=False)

    start = get_now() - timedelta(minutes=30)
    rec = Recurrence(
        id=0,
        type=RecurrenceType.Weekly,
        first_start=start,
        duration_seconds=3600,
    )
    entry = CalendarEntry(
        title="Task",
        description="",
        type=CalendarEntryType.Chore,
        recurrences=[rec],
        responsible=["Admin"],
        managers=["Admin"],
    )
    app_module.calendar_store.create(entry)
    entry_id = app_module.calendar_store.list_entries()[0].id

    resp = client.post(
        f"/calendar/{entry_id}/duration",
        data={
            "recurrence_id": 0,
            "instance_index": 0,
            "duration_days": "",
            "duration_hours": "2",
            "duration_minutes": "",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303

    page = client.get(f"/calendar/entry/{entry_id}/period/0/0")
    assert "Duration" in page.text
    assert "2:00" in page.text

    entry = app_module.calendar_store.get(entry_id)
    period = next(enumerate_time_periods(entry))
    assert (period.end - period.start) == timedelta(hours=2)

    home = client.get("/")
    end_ts = int(period.end.timestamp())
    assert f'data-end="{end_ts}' in home.text
