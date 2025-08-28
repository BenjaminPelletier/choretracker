import importlib
import sys
from pathlib import Path
from datetime import datetime, timedelta

from fastapi.testclient import TestClient

# Ensure project root on path
sys.path.append(str(Path(__file__).resolve().parents[1]))

from choretracker.calendar import CalendarEntry, CalendarEntryType, Recurrence, RecurrenceType, Delegation
from itertools import islice


def test_description_edit_splits_entry(tmp_path, monkeypatch):
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("CHORETRACKER_DB", str(db_file))
    if "choretracker.app" in sys.modules:
        del sys.modules["choretracker.app"]
    app_module = importlib.import_module("choretracker.app")

    fake_now = datetime(2025, 1, 15, 0, 0)

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fake_now if tz is None else fake_now.astimezone(tz)

    monkeypatch.setattr(app_module, "datetime", FixedDateTime)
    import choretracker.calendar as cal_mod
    monkeypatch.setattr(cal_mod, "datetime", FixedDateTime)

    client = TestClient(app_module.app)
    client.post("/login", data={"username": "Admin", "password": "admin"}, follow_redirects=False)

    first_start = fake_now - timedelta(days=14)
    rec = Recurrence(
        type=RecurrenceType.Weekly,
        skipped_instances=[0, 2],
        delegations=[Delegation(instance_index=0, responsible=["A"]), Delegation(instance_index=1, responsible=["B"])]
    )
    entry = CalendarEntry(
        title="Task",
        description="Old",
        type=CalendarEntryType.Chore,
        first_start=first_start,
        duration_seconds=60,
        recurrences=[rec],
        managers=["Admin"],
        responsible=["Admin"],
    )
    app_module.calendar_store.create(entry)
    entry_id = app_module.calendar_store.list_entries()[0].id

    # completions
    app_module.completion_store.create(entry_id, 0, 0, "Admin")
    app_module.completion_store.create(entry_id, 0, 1, "Admin")

    resp = client.post(
        f"/calendar/{entry_id}/update", json={"description": "New"}
    )
    data = resp.json()

    entries = sorted(app_module.calendar_store.list_entries(), key=lambda e: e.id)
    old_entry = next(e for e in entries if e.id == entry_id)
    new_entry = next(e for e in entries if e.id != entry_id)

    assert data["redirect"] == f"../entry/{new_entry.id}"

    assert old_entry.description == "Old"
    assert new_entry.description == "New"
    assert old_entry.none_after == fake_now - timedelta(minutes=1)
    assert new_entry.none_before == fake_now

    assert old_entry.recurrences[0].skipped_instances == [0]
    assert new_entry.recurrences[0].skipped_instances == [2]
    assert [d.instance_index for d in old_entry.recurrences[0].delegations] == [0]
    assert [d.instance_index for d in new_entry.recurrences[0].delegations] == [1]

    old_comps = app_module.completion_store.list_for_entry(old_entry.id)
    new_comps = app_module.completion_store.list_for_entry(new_entry.id)
    assert {(c.recurrence_index, c.instance_index) for c in old_comps} == {(0, 0)}
    assert {(c.recurrence_index, c.instance_index) for c in new_comps} == {(0, 1)}

    # new linking fields
    assert old_entry.next_entry == new_entry.id
    assert new_entry.previous_entry == old_entry.id

    # ensure previous/next links show on pages
    old_start, old_end = app_module.entry_time_bounds(old_entry)
    new_start, new_end = app_module.entry_time_bounds(new_entry)

    page_old = client.get(f"/calendar/entry/{old_entry.id}")
    next_summary = app_module.time_range_summary(new_start, new_end)
    assert (
        f'Next: <a href="./{new_entry.id}">{next_summary}</a>'
        in page_old.text
    )

    page_new = client.get(f"/calendar/entry/{new_entry.id}")
    prev_summary = app_module.time_range_summary(old_start, old_end)
    assert (
        f'Previous: <a href="./{old_entry.id}">{prev_summary}</a>'
        in page_new.text
    )

    page = client.get(f"/calendar/entry/{new_entry.id}")
    expected_nb = fake_now.strftime("%A %Y-%m-%d %H:%M")
    assert (
        f'None before: <span id="none-before-text">{expected_nb}</span>' in page.text
    )

    # ensure instances split
    old_times = [p.start for p in app_module.enumerate_time_periods(old_entry)]
    new_times = [p.start for p in islice(app_module.enumerate_time_periods(new_entry), 5)]
    assert max(old_times) < fake_now
    assert min(new_times) >= fake_now
