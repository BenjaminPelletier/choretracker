import importlib
import sys
from pathlib import Path
from fastapi.testclient import TestClient

from choretracker.time_utils import get_now
from choretracker.calendar import CalendarEntry, CalendarEntryType, Recurrence, RecurrenceType
from sqlmodel import Session

# Ensure project root is on path
sys.path.append(str(Path(__file__).resolve().parents[1]))

def test_view_entry_no_next_start(tmp_path, monkeypatch):
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("CHORETRACKER_DB", str(db_file))
    if "choretracker.app" in sys.modules:
        del sys.modules["choretracker.app"]
    app_module = importlib.import_module("choretracker.app")

    client = TestClient(app_module.app)
    client.post("/login", data={"username": "Admin", "password": "admin"}, follow_redirects=False)

    now = get_now()
    entry1 = CalendarEntry(
        title="Base",
        description="",
        type=CalendarEntryType.Event,
        first_start=now,
        duration_seconds=60,
        managers=["Admin"],
    )
    app_module.calendar_store.create(entry1)
    entry1_id = app_module.calendar_store.list_entries()[0].id

    entry2 = CalendarEntry(
        title="Next",
        description="",
        type=CalendarEntryType.Event,
        recurrences=[Recurrence(type=RecurrenceType.OneTime)],
        managers=["Admin"],
    )
    app_module.calendar_store.create(entry2)
    entry2_id = sorted([e.id for e in app_module.calendar_store.list_entries() if e.id != entry1_id])[0]

    with Session(app_module.engine) as session:
        e1 = session.get(CalendarEntry, entry1_id)
        e2 = session.get(CalendarEntry, entry2_id)
        e1.next_entry = e2.id
        e2.previous_entry = e1.id
        session.add(e1)
        session.add(e2)
        session.commit()

    resp = client.get(f"/calendar/entry/{entry1_id}")
    assert resp.status_code == 200
    assert "Next:" not in resp.text
