import sys
import importlib
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

# Ensure project root on path
sys.path.append(str(Path(__file__).resolve().parents[1]))

@pytest.mark.parametrize("entry_type", ["Event", "Reminder", "Chore"])
def test_new_entry_form_action(tmp_path, monkeypatch, entry_type):
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("CHORETRACKER_DB", str(db_file))
    monkeypatch.setenv("CHORETRACKER_SECRET_KEY", "test")
    monkeypatch.setenv("CHORETRACKER_DISABLE_CSRF", "1")
    if "choretracker.app" in sys.modules:
        del sys.modules["choretracker.app"]
    app_module = importlib.import_module("choretracker.app")

    client = TestClient(app_module.app)
    client.post("/login", data={"username": "Admin", "password": "admin"}, follow_redirects=False)

    resp = client.get(f"/calendar/new/{entry_type}")
    assert resp.status_code == 200
    assert 'action="/calendar/new"' in resp.text
