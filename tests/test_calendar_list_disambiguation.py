import importlib
import sys
from pathlib import Path
from datetime import datetime

from fastapi.testclient import TestClient

# Ensure project root is on path
sys.path.append(str(Path(__file__).resolve().parents[1]))

from choretracker.calendar import CalendarEntry, CalendarEntryType


def test_duplicate_titles_disambiguated(tmp_path, monkeypatch):
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("CHORETRACKER_DB", str(db_file))
    app_module = importlib.import_module("choretracker.app")
    client = TestClient(app_module.app)

    client.post("/login", data={"username": "Admin", "password": "admin"}, follow_redirects=False)

    first = CalendarEntry(
        title="Guinea salad",
        description="",
        type=CalendarEntryType.Event,
        first_start=datetime(2025, 8, 22, 8, 0, 0),
        duration_seconds=60,
        managers=["Admin"],
    )
    second = CalendarEntry(
        title="Guinea salad",
        description="",
        type=CalendarEntryType.Event,
        first_start=datetime(2025, 8, 23, 8, 0, 0),
        duration_seconds=60,
        managers=["Admin"],
    )
    app_module.calendar_store.create(first)
    app_module.calendar_store.create(second)

    response = client.get("/calendar/list/Event")
    assert "Guinea salad (Friday 2025-08-22 08:00)" in response.text
    assert "Guinea salad (Saturday 2025-08-23 08:00)" in response.text
