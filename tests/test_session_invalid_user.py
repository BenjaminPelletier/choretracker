import importlib
import sys
from pathlib import Path

from fastapi.testclient import TestClient

# Ensure project root on path
sys.path.append(str(Path(__file__).resolve().parents[1]))


def test_deleted_user_logs_out(tmp_path, monkeypatch):
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("CHORETRACKER_DB", str(db_file))
    if "choretracker.app" in sys.modules:
        del sys.modules["choretracker.app"]
    app_module = importlib.import_module("choretracker.app")

    client = TestClient(app_module.app)

    # Create and login as a temporary user
    app_module.user_store.create("Temp", "temp", None, set())
    client.post("/login", data={"username": "Temp", "password": "temp"}, follow_redirects=False)

    # Remove the user from the store
    app_module.user_store.delete("Temp")

    # Access a protected endpoint; should redirect to login and clear session
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code in (303, 307)
    assert resp.headers["location"] == "/login"

    # Session should be cleared; login page should not redirect
    resp = client.get("/login", follow_redirects=False)
    assert resp.status_code == 200
