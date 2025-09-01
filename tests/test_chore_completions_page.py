import importlib
import sys
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

# Ensure project root on path
sys.path.append(str(Path(__file__).resolve().parents[1]))


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


def test_chore_completions_sections(tmp_path, monkeypatch):
    fake_now = datetime(2000, 1, 3, 12, 0, tzinfo=ZoneInfo("UTC"))
    app_module, client = _setup_app(tmp_path, monkeypatch, fake_now)

    entry = app_module.CalendarEntry(
        title="Task",
        description="",
        type=app_module.CalendarEntryType.Chore,
        first_start=fake_now - timedelta(days=5),
        duration_seconds=60,
        managers=["Admin"],
    )
    app_module.calendar_store.create(entry)
    entry_id = app_module.calendar_store.list_entries()[0].id

    app_module.completion_store.create(
        entry_id, -1, -1, "Admin", completed_at=fake_now - timedelta(hours=1)
    )
    app_module.completion_store.create(
        entry_id, -1, -1, "Admin", completed_at=fake_now - timedelta(days=1, hours=1)
    )
    app_module.completion_store.create(
        entry_id, -1, -1, "Admin", completed_at=fake_now - timedelta(days=2)
    )

    response = client.get("/chore_completions")
    text = response.text
    assert "Today" in text
    assert "Yesterday" in text
    assert "Earlier" in text
    t1 = app_module.format_datetime(fake_now - timedelta(hours=1), True)
    t2 = app_module.format_datetime(fake_now - timedelta(days=1, hours=1), True)
    t3 = app_module.format_datetime(fake_now - timedelta(days=2), True)
    assert text.index(t1) < text.index(t2) < text.index(t3)


def test_nav_shows_completion_icon(tmp_path, monkeypatch):
    fake_now = datetime(2000, 1, 1, 0, 0, tzinfo=ZoneInfo("UTC"))
    app_module, client = _setup_app(tmp_path, monkeypatch, fake_now)
    response = client.get("/")
    text = response.text
    home_idx = text.index("home.svg")
    comp_idx = text.index("checkbox-checked.svg")
    assert home_idx < comp_idx
    assert 'href="./chore_completions"' in text

