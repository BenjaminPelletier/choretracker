import importlib
import sys
from pathlib import Path
from datetime import timedelta
from choretracker.time_utils import get_now

from fastapi.testclient import TestClient

# Ensure project root is on path
sys.path.append(str(Path(__file__).resolve().parents[1]))

from choretracker.calendar import (
    CalendarEntry,
    CalendarEntryType,
    Recurrence,
    RecurrenceType,
)


def test_list_active_and_past(tmp_path, monkeypatch):
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("CHORETRACKER_DB", str(db_file))
    app_module = importlib.import_module("choretracker.app")
    client = TestClient(app_module.app)

    client.post("/login", data={"username": "Admin", "password": "admin"}, follow_redirects=False)

    now = get_now()
    active_newer = CalendarEntry(
        title="Future 2",
        description="",
        type=CalendarEntryType.Event,
        recurrences=[
            Recurrence(
                id=0,
                type=RecurrenceType.OneTime,
                first_start=now + timedelta(days=2),
                duration_seconds=60,
            )
        ],
        managers=["Admin"],
    )
    active_older = CalendarEntry(
        title="Future 1",
        description="",
        type=CalendarEntryType.Event,
        recurrences=[
            Recurrence(
                id=0,
                type=RecurrenceType.OneTime,
                first_start=now + timedelta(days=1),
                duration_seconds=60,
            )
        ],
        managers=["Admin"],
    )
    past_newer = CalendarEntry(
        title="Past 1",
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
    past_older = CalendarEntry(
        title="Past 2",
        description="",
        type=CalendarEntryType.Event,
        recurrences=[
            Recurrence(
                id=0,
                type=RecurrenceType.OneTime,
                first_start=now - timedelta(days=2),
                duration_seconds=60,
            )
        ],
        managers=["Admin"],
    )
    app_module.calendar_store.create(active_newer)
    app_module.calendar_store.create(active_older)
    app_module.calendar_store.create(past_newer)
    app_module.calendar_store.create(past_older)

    response = client.get("/calendar/list/Event")
    text = response.text
    assert "<h2>Active</h2>" in text
    assert "<h2>Past</h2>" in text
    active_idx = text.index("<h2>Active</h2>")
    past_idx = text.index("<h2>Past</h2>")
    assert active_idx < past_idx
    idx_future2 = text.index("Future 2")
    idx_future1 = text.index("Future 1")
    assert idx_future2 < idx_future1
    idx_past1 = text.index("Past 1")
    idx_past2 = text.index("Past 2")
    assert idx_past1 < idx_past2
    assert idx_future2 < past_idx
    assert idx_past1 > past_idx
