import importlib
import sys
from pathlib import Path
from datetime import datetime

from fastapi.testclient import TestClient

# Ensure project root is on path
sys.path.append(str(Path(__file__).resolve().parents[1]))

from choretracker.calendar import CalendarEntry, CalendarEntryType


def test_description_rendered_as_markdown(tmp_path, monkeypatch):
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("CHORETRACKER_DB", str(db_file))
    app_module = importlib.import_module("choretracker.app")
    client = TestClient(app_module.app)

    client.post("/login", data={"username": "Admin", "password": "admin"}, follow_redirects=False)

    entry = CalendarEntry(
        title="Markdown",
        description="**bold**",
        type=CalendarEntryType.Event,
        first_start=datetime(2025, 1, 1, 0, 0, 0),
        duration_seconds=60,
    )
    app_module.calendar_store.create(entry)
    entry_id = app_module.calendar_store.list_entries()[-1].id

    response = client.get(f"/calendar/entry/{entry_id}")
    assert "<strong>bold</strong>" in response.text
    assert "**bold**" not in response.text
