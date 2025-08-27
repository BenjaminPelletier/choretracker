import importlib
import sys
from pathlib import Path

from fastapi.testclient import TestClient

# Ensure project root on path
sys.path.append(str(Path(__file__).resolve().parents[1]))


def _load_app(tmp_path, monkeypatch):
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("CHORETRACKER_DB", str(db_file))
    if "choretracker.app" in sys.modules:
        del sys.modules["choretracker.app"]
    return importlib.import_module("choretracker.app")


def test_system_page_shows_version(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORETRACKER_VERSION", "v1.2.3")
    app_module = _load_app(tmp_path, monkeypatch)
    client = TestClient(app_module.app)
    client.post("/login", data={"username": "Admin", "password": "admin"}, follow_redirects=False)
    resp = client.get("/system")
    assert resp.status_code == 200
    assert "choretracker" in resp.text
    assert "v1.2.3" in resp.text


def test_system_page_requires_admin(tmp_path, monkeypatch):
    app_module = _load_app(tmp_path, monkeypatch)
    app_module.user_store.create("User", "pw", None, set())
    client = TestClient(app_module.app)
    client.post("/login", data={"username": "User", "password": "pw"}, follow_redirects=False)
    resp = client.get("/system", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"].endswith("/")
