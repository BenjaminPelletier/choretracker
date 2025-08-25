import importlib
import sys
from pathlib import Path
from datetime import datetime
import re

from fastapi.testclient import TestClient

# Ensure project root on path
sys.path.append(str(Path(__file__).resolve().parents[1]))

from choretracker.calendar import CalendarEntry, CalendarEntryType, Recurrence, RecurrenceType


def test_instances_past_and_upcoming(tmp_path, monkeypatch):
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("CHORETRACKER_DB", str(db_file))
    if "choretracker.app" in sys.modules:
        del sys.modules["choretracker.app"]
    app_module = importlib.import_module("choretracker.app")

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2000, 1, 22, 0, 0, 0)

    monkeypatch.setattr(app_module, "datetime", FixedDatetime)
    import choretracker.calendar as calendar_module
    monkeypatch.setattr(calendar_module, "datetime", FixedDatetime)

    client = TestClient(app_module.app)
    client.post("/login", data={"username": "Admin", "password": "admin"}, follow_redirects=False)

    entry = CalendarEntry(
        title="Dishes",
        description="",
        type=CalendarEntryType.Chore,
        first_start=datetime(2000, 1, 1, 0, 0, 0),
        duration_seconds=3600,
        recurrences=[
            Recurrence(type=RecurrenceType.Weekly, skipped_instances=[1])
        ],
        responsible=["Bob"],
        managers=["Admin"],
    )
    app_module.calendar_store.create(entry)
    entry_id = app_module.calendar_store.list_entries()[0].id

    # complete the third instance early (start 2000-01-22)
    app_module.completion_store.create(entry_id, 0, 2, "Admin")

    response = client.get(f"/calendar/entry/{entry_id}")
    text = response.text
    assert "<h2>Instances</h2>" in text
    assert "Past" in text and "Upcoming" in text
    # early completion should show under Past and be linked
    assert (
        f'<a href="http://testserver/calendar/entry/{entry_id}/period/0/2">Due Saturday 2000-01-22 01:00</a>'
        in text
    )
    # skipped past instance is listed with annotation and responsible profile
    assert (
        f'<a href="http://testserver/calendar/entry/{entry_id}/period/0/1">Due Saturday 2000-01-15 01:00</a>'
        in text
    )
    assert "(skipped)" in text
    # first upcoming instance is linked
    assert (
        f'<a href="http://testserver/calendar/entry/{entry_id}/period/0/3">Due Saturday 2000-01-29 01:00</a>'
        in text
    )
    # profile icons for completed and responsible users displayed
    assert "/users/Admin/profile_picture" in text
    assert "/users/Bob/profile_picture" in text
    # Responsible icon should appear before completion details
    line = re.search(
        rf'<a href="http://testserver/calendar/entry/{entry_id}/period/0/2">Due Saturday 2000-01-22 01:00</a>(.*?)</li>',
        text,
        re.DOTALL,
    ).group(1)
    assert line.index('/users/Bob/profile_picture') < line.index('checkbox-checked.svg')
