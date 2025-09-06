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
    InstanceSpecifics,
)


def test_entry_not_deleted_with_completion(tmp_path, monkeypatch):
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("CHORETRACKER_DB", str(db_file))
    if "choretracker.app" in sys.modules:
        del sys.modules["choretracker.app"]
    app_module = importlib.import_module("choretracker.app")
    now = get_now()
    rec = Recurrence(
        id=0,
        type=RecurrenceType.OneTime,
        first_start=now,
        duration_seconds=60,
    )
    entry = CalendarEntry(
        title="Chore",
        description="",
        type=CalendarEntryType.Chore,
        recurrences=[rec],
        managers=["Admin"],
        responsible=["Admin"],
    )
    app_module.calendar_store.create(entry)
    entry_id = app_module.calendar_store.list_entries()[0].id
    app_module.completion_store.create(entry_id, 0, 0, "Admin")
    assert app_module.completion_store.list_for_entry(entry_id)
    assert not app_module.calendar_store.delete(entry_id)
    assert app_module.calendar_store.get(entry_id) is not None
    assert app_module.completion_store.list_for_entry(entry_id)


def test_entry_not_deleted_with_delegation(tmp_path, monkeypatch):
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("CHORETRACKER_DB", str(db_file))
    if "choretracker.app" in sys.modules:
        del sys.modules["choretracker.app"]
    app_module = importlib.import_module("choretracker.app")
    now = get_now()
    rec = Recurrence(
        id=0,
        type=RecurrenceType.Weekly,
        first_start=now,
        duration_seconds=60,
    )
    rec.instance_specifics[0] = InstanceSpecifics(
        entry_id=0,
        recurrence_id=0,
        instance_index=0,
        responsible=["Admin"],
    )
    entry = CalendarEntry(
        title="Delegated",
        description="",
        type=CalendarEntryType.Chore,
        recurrences=[rec],
        managers=["Admin"],
        responsible=["Admin"],
    )
    app_module.calendar_store.create(entry)
    entry_id = app_module.calendar_store.list_entries()[0].id
    assert not app_module.calendar_store.delete(entry_id)
    assert app_module.calendar_store.get(entry_id) is not None


def test_list_hides_delete_for_undeletable(tmp_path, monkeypatch):
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("CHORETRACKER_DB", str(db_file))
    if "choretracker.app" in sys.modules:
        del sys.modules["choretracker.app"]
    app_module = importlib.import_module("choretracker.app")
    client = TestClient(app_module.app)
    client.post("/login", data={"username": "Admin", "password": "admin"}, follow_redirects=False)
    now = get_now()
    rec1 = Recurrence(
        id=0,
        type=RecurrenceType.OneTime,
        first_start=now,
        duration_seconds=60,
    )
    rec2 = Recurrence(
        id=0,
        type=RecurrenceType.OneTime,
        first_start=now,
        duration_seconds=60,
    )
    rec3 = Recurrence(
        id=0,
        type=RecurrenceType.Weekly,
        first_start=now - timedelta(days=7),
        duration_seconds=60,
    )
    with_completion = CalendarEntry(
        title="With",
        description="",
        type=CalendarEntryType.Chore,
        recurrences=[rec1],
        managers=["Admin"],
        responsible=["Admin"],
    )
    without_completion = CalendarEntry(
        title="Without",
        description="",
        type=CalendarEntryType.Chore,
        recurrences=[rec2],
        managers=["Admin"],
        responsible=["Admin"],
    )
    past_entry = CalendarEntry(
        title="Past",
        description="",
        type=CalendarEntryType.Chore,
        recurrences=[rec3],
        managers=["Admin"],
        responsible=["Admin"],
    )
    app_module.calendar_store.create(with_completion)
    app_module.calendar_store.create(without_completion)
    app_module.calendar_store.create(past_entry)
    entries = app_module.calendar_store.list_entries()
    ids = {e.title: e.id for e in entries}
    comp_id = ids["With"]
    del_id = ids["Without"]
    past_id = ids["Past"]
    app_module.completion_store.create(comp_id, 0, 0, "Admin")
    resp = client.get("/calendar/list/Chore")
    text = resp.text
    assert f"../{comp_id}/delete" not in text
    assert f"../{del_id}/delete" in text
    assert f"../{past_id}/delete" not in text


def test_entry_with_past_instances_not_deleted(tmp_path, monkeypatch):
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("CHORETRACKER_DB", str(db_file))
    if "choretracker.app" in sys.modules:
        del sys.modules["choretracker.app"]
    app_module = importlib.import_module("choretracker.app")
    now = get_now()
    rec = Recurrence(
        id=0,
        type=RecurrenceType.Weekly,
        first_start=now - timedelta(days=7),
        duration_seconds=60,
    )
    entry = CalendarEntry(
        title="Past",
        description="",
        type=CalendarEntryType.Event,
        recurrences=[rec],
        managers=["Admin"],
    )
    app_module.calendar_store.create(entry)
    entry_id = app_module.calendar_store.list_entries()[0].id
    assert not app_module.calendar_store.delete(entry_id)


def test_linked_entry_deletion_updates_previous(tmp_path, monkeypatch):
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("CHORETRACKER_DB", str(db_file))
    if "choretracker.app" in sys.modules:
        del sys.modules["choretracker.app"]
    app_module = importlib.import_module("choretracker.app")
    now = get_now()
    rec = Recurrence(
        id=0,
        type=RecurrenceType.OneTime,
        first_start=now,
        duration_seconds=60,
    )
    entry = CalendarEntry(
        title="Original",
        description="",
        type=CalendarEntryType.Chore,
        recurrences=[rec],
        managers=["Admin"],
        responsible=["Admin"],
    )
    app_module.calendar_store.create(entry)
    entry_id = app_module.calendar_store.list_entries()[0].id
    split_time = now + timedelta(days=1)
    new_entry = app_module.calendar_store.split(entry_id, split_time)
    assert app_module.calendar_store.delete(entry_id)
    assert app_module.calendar_store.get(entry_id) is None
    remaining = app_module.calendar_store.get(new_entry.id)
    assert remaining.previous_entry is None


def test_delete_middle_entry_relinks_neighbors(tmp_path, monkeypatch):
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("CHORETRACKER_DB", str(db_file))
    if "choretracker.app" in sys.modules:
        del sys.modules["choretracker.app"]
    app_module = importlib.import_module("choretracker.app")
    now = get_now()
    rec = Recurrence(
        id=0,
        type=RecurrenceType.OneTime,
        first_start=now,
        duration_seconds=60,
    )
    entry = CalendarEntry(
        title="Start",
        description="",
        type=CalendarEntryType.Chore,
        recurrences=[rec],
        managers=["Admin"],
        responsible=["Admin"],
    )
    app_module.calendar_store.create(entry)
    entry_id = app_module.calendar_store.list_entries()[0].id
    split1 = now + timedelta(days=1)
    second = app_module.calendar_store.split(entry_id, split1)
    split2 = now + timedelta(days=2)
    third = app_module.calendar_store.split(second.id, split2)
    assert app_module.calendar_store.delete(second.id)
    first = app_module.calendar_store.get(entry_id)
    last = app_module.calendar_store.get(third.id)
    assert first.next_entry == last.id
    assert last.previous_entry == first.id
