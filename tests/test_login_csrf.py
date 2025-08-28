import importlib
import sys
import re
from pathlib import Path

from fastapi.testclient import TestClient

# Ensure project root on path
sys.path.append(str(Path(__file__).resolve().parents[1]))


def test_login_requires_csrf(tmp_path, monkeypatch):
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("CHORETRACKER_DB", str(db_file))
    monkeypatch.setenv("CHORETRACKER_SECRET_KEY", "test")
    monkeypatch.delenv("CHORETRACKER_DISABLE_CSRF", raising=False)

    if "choretracker.app" in sys.modules:
        del sys.modules["choretracker.app"]
    app_module = importlib.import_module("choretracker.app")

    client = TestClient(app_module.app)

    resp = client.get("/login")
    assert resp.status_code == 200
    match = re.search(r'name="csrf_token" value="([^"]+)"', resp.text)
    assert match is not None
    token = match.group(1)

    resp = client.post("/login", data={"username": "Admin", "password": "admin"})
    assert resp.status_code == 400
    assert "Invalid CSRF token" in resp.text

    resp = client.post(
        "/login",
        data={"username": "Admin", "password": "admin", "csrf_token": token},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"
