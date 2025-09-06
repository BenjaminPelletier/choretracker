import importlib
import sys
from pathlib import Path
from datetime import datetime, timedelta
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
    return app_module, client


def test_single_instance_link_points_to_entry(tmp_path, monkeypatch):
    fake_now = datetime(2000, 1, 1, tzinfo=ZoneInfo("UTC"))
    app_module, client = _setup_app(tmp_path, monkeypatch, fake_now)

    start = fake_now - timedelta(minutes=5)
    entry = CalendarEntry(
        title="Single",
        description="",
        type=CalendarEntryType.Event,
        recurrences=[
            Recurrence(
                id=0,
                type=RecurrenceType.OneTime,
                first_start=start,
                duration_seconds=600,
            )
        ],
        managers=["Admin"],
        responsible=["Admin"],
    )
    app_module.calendar_store.create(entry)
    entry_id = app_module.calendar_store.list_entries()[0].id

    resp = client.get("/")
    assert f"/calendar/entry/{entry_id}" in resp.text
    assert f"/calendar/entry/{entry_id}/period/" not in resp.text

