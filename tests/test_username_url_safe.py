import importlib
import sys
from pathlib import Path

from fastapi.testclient import TestClient

# Ensure project root on path
sys.path.append(str(Path(__file__).resolve().parents[1]))


def test_url_unsafe_usernames_rejected(tmp_path, monkeypatch):
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("CHORETRACKER_DB", str(db_file))
    if "choretracker.app" in sys.modules:
        del sys.modules["choretracker.app"]
    app_module = importlib.import_module("choretracker.app")

    client = TestClient(app_module.app)
    client.post("/login", data={"username": "Admin", "password": "admin"}, follow_redirects=False)

    resp = client.post("/users/new", data={"username": "bad/name"}, follow_redirects=False)
    assert resp.status_code == 303
    assert app_module.user_store.get("bad/name") is None

    resp = client.post("/users/new", data={"username": "Good"}, follow_redirects=False)
    assert resp.status_code == 303
    assert app_module.user_store.get("Good") is not None

    resp = client.post("/users/Good/edit", data={"username": "Bad Name"}, follow_redirects=False)
    assert resp.status_code == 303
    assert app_module.user_store.get("Good") is not None
