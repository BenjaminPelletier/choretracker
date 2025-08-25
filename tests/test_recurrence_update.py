import importlib
import sys
from pathlib import Path
from datetime import datetime

from fastapi.testclient import TestClient


# Ensure project root on path
sys.path.append(str(Path(__file__).resolve().parents[1]))

from choretracker.calendar import (
    CalendarEntry,
    CalendarEntryType,
    Recurrence,
    RecurrenceType,
    Offset,
)


def test_update_recurrence_responsible_and_offset(tmp_path, monkeypatch):
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

    entry = CalendarEntry(
        title="RecTest",
        description="",
        type=CalendarEntryType.Chore,
        first_start=datetime(2000, 1, 1, 0, 0),
        duration_seconds=60,
        recurrences=[
            Recurrence(
                type=RecurrenceType.Weekly,
                offset=Offset(exact_duration_seconds=3600),
                responsible=["Alice"],
            )
        ],
    )
    app_module.calendar_store.create(entry)
    entry_id = app_module.calendar_store.list_entries()[0].id

    resp = client.post(
        f"/calendar/{entry_id}/recurrence/update",
        json={
            "recurrence_index": 0,
            "type": "Weekly",
            "offset_days": 0,
            "offset_hours": 2,
            "offset_minutes": 30,
            "responsible": ["Bob"],
        },
    )
    assert resp.status_code == 200

    updated = app_module.calendar_store.get(entry_id)
    rec = updated.recurrences[0]
    assert rec.responsible == ["Bob"]
    assert rec.offset and rec.offset.exact_duration_seconds == 2 * 3600 + 30 * 60

