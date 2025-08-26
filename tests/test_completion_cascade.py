import importlib
import sys
from pathlib import Path
from datetime import datetime

# Ensure project root is on path
sys.path.append(str(Path(__file__).resolve().parents[1]))

from choretracker.calendar import CalendarEntry, CalendarEntryType


def test_completion_deleted_with_entry(tmp_path, monkeypatch):
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("CHORETRACKER_DB", str(db_file))
    app_module = importlib.import_module("choretracker.app")
    now = datetime.now()
    entry = CalendarEntry(
        title="Chore",
        description="",
        type=CalendarEntryType.Chore,
        first_start=now,
        duration_seconds=60,
        managers=["Admin"],
    )
    app_module.calendar_store.create(entry)
    entry_id = app_module.calendar_store.list_entries()[0].id
    app_module.completion_store.create(entry_id, 0, 0, "Admin")
    assert app_module.completion_store.list_for_entry(entry_id)
    app_module.calendar_store.delete(entry_id)
    assert not app_module.completion_store.list_for_entry(entry_id)
