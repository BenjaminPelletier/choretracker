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
    client.post("/login", data={"username": "Admin", "password": "admin"}, follow_redirects=False)
    return app_module, client


def test_now_sorting(tmp_path, monkeypatch):
    fake_now = datetime(2000, 1, 1, 0, 0, 0, tzinfo=ZoneInfo("UTC"))
    app_module, client = _setup_app(tmp_path, monkeypatch, fake_now)

    start = fake_now - timedelta(minutes=5)
    entries = [
        CalendarEntry(
            title="Beta",
            description="",
            type=CalendarEntryType.Chore,
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
        ),
        CalendarEntry(
            title="Gamma",
            description="",
            type=CalendarEntryType.Chore,
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
        ),
        CalendarEntry(
            title="Alpha",
            description="",
            type=CalendarEntryType.Chore,
            recurrences=[
                Recurrence(
                    id=0,
                    type=RecurrenceType.OneTime,
                    first_start=start,
                    duration_seconds=900,
                )
            ],
            managers=["Admin"],
            responsible=["Admin"],
        ),
        CalendarEntry(
            title="Zeta",
            description="",
            type=CalendarEntryType.Chore,
            recurrences=[
                Recurrence(
                    id=0,
                    type=RecurrenceType.OneTime,
                    first_start=start,
                    duration_seconds=360,
                )
            ],
            managers=["Admin"],
            responsible=["Admin"],
        ),
    ]
    for entry in entries:
        app_module.calendar_store.create(entry)

    id_map = {e.title: e.id for e in app_module.calendar_store.list_entries()}
    app_module.completion_store.create(id_map["Zeta"], 0, 0, "Admin")

    response = client.get("/")
    text = response.text
    assert text.index("Beta") < text.index("Gamma") < text.index("Alpha") < text.index("Zeta")


def test_overdue_sorting(tmp_path, monkeypatch):
    fake_now = datetime(2000, 1, 1, 0, 0, 0, tzinfo=ZoneInfo("UTC"))
    app_module, client = _setup_app(tmp_path, monkeypatch, fake_now)

    entries = [
        CalendarEntry(
            title="Alpha",
            description="",
            type=CalendarEntryType.Chore,
            recurrences=[
                Recurrence(
                    id=0,
                    type=RecurrenceType.OneTime,
                    first_start=fake_now - timedelta(minutes=20),
                    duration_seconds=300,
                )
            ],
            managers=["Admin"],
            responsible=["Admin"],
        ),
        CalendarEntry(
            title="Beta",
            description="",
            type=CalendarEntryType.Chore,
            recurrences=[
                Recurrence(
                    id=0,
                    type=RecurrenceType.OneTime,
                    first_start=fake_now - timedelta(minutes=10),
                    duration_seconds=300,
                )
            ],
            managers=["Admin"],
            responsible=["Admin"],
        ),
        CalendarEntry(
            title="Gamma",
            description="",
            type=CalendarEntryType.Chore,
            recurrences=[
                Recurrence(
                    id=0,
                    type=RecurrenceType.OneTime,
                    first_start=fake_now - timedelta(minutes=10),
                    duration_seconds=300,
                )
            ],
            managers=["Admin"],
            responsible=["Admin"],
        ),
    ]
    for entry in entries:
        app_module.calendar_store.create(entry)

    response = client.get("/")
    text = response.text
    assert text.index("Alpha") < text.index("Beta") < text.index("Gamma")
