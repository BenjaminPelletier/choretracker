import importlib
import sys
from datetime import timedelta
from pathlib import Path
from unittest.mock import Mock

from fastapi.testclient import TestClient
from sqlmodel import Session, select

sys.path.append(str(Path(__file__).resolve().parents[1]))

from choretracker.calendar import CalendarEntry, CalendarEntryType, Recurrence, RecurrenceType
from choretracker.users import User


def test_home_reuses_entries_and_permissions_without_stale_permissions(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORETRACKER_DB", str(tmp_path / "test.db"))
    sys.modules.pop("choretracker.app", None)
    module = importlib.import_module("choretracker.app")
    now = module.get_now()
    for i in range(5):
        module.calendar_store.create(CalendarEntry(
            title=f"Overdue {i}",
            type=CalendarEntryType.Chore,
            managers=["Admin"],
            responsible=["Admin"],
            recurrences=[Recurrence(
                id=0, type=RecurrenceType.OneTime,
                first_start=now - timedelta(days=1), duration_seconds=60,
            )],
        ))
    client = TestClient(module.app)
    client.post("/login", data={"username": "Admin", "password": "admin"}, follow_redirects=False)
    client.post("/switch/Viewer")
    list_entries = Mock(wraps=module.calendar_store.list_entries)
    permissions = Mock(wraps=module.user_store.get_permissions)
    monkeypatch.setattr(module.calendar_store, "list_entries", list_entries)
    monkeypatch.setattr(module.user_store, "get_permissions", permissions)

    response = client.get("/")
    assert response.status_code == 200
    assert "Overdue 4" in response.text
    assert "checkbox-checked.svg" in response.text  # completion-history navigation
    list_entries.assert_called_once()
    permissions.assert_called_once_with("Viewer")

    with Session(module.engine) as session:
        viewer = session.exec(select(User).where(User.username == "Viewer")).one()
        viewer.permissions = []
        session.add(viewer)
        session.commit()
    response = client.get("/")
    assert response.status_code == 200
    assert "checkbox-checked.svg" not in response.text.split("<main")[0]
    assert permissions.call_count == 2
    assert list_entries.call_count == 2


def test_completion_summaries_preserve_keys_and_local_time(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORETRACKER_DB", str(tmp_path / "test.db"))
    sys.modules.pop("choretracker.app", None)
    module = importlib.import_module("choretracker.app")
    now = module.get_now()
    entry = CalendarEntry(
        title="Chore", type=CalendarEntryType.Chore, managers=["Admin"],
        recurrences=[Recurrence(id=0, type=RecurrenceType.Weekly,
                                first_start=now, duration_seconds=60)],
    )
    module.calendar_store.create(entry)
    entry_id = module.calendar_store.list_entries()[0].id
    module.completion_store.create(entry_id, 0, 0, "Admin", completed_at=now)
    module.completion_store.create(entry_id, 0, 1, "Admin", completed_at=now - timedelta(days=30))
    summaries = module.completion_store.summaries()
    assert set(summaries) == {(entry_id, 0, 0), (entry_id, 0, 1)}
    assert summaries[entry_id, 0, 0].completed_by == "Admin"
    assert summaries[entry_id, 0, 0].completed_at == now
    assert summaries[entry_id, 0, 1].completed_at == now - timedelta(days=30)
