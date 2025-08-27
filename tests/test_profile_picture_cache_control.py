import importlib
import sys
from pathlib import Path

from fastapi.testclient import TestClient

# Ensure project root on path
sys.path.append(str(Path(__file__).resolve().parents[1]))


def test_profile_picture_not_cached(tmp_path, monkeypatch):
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("CHORETRACKER_DB", str(db_file))
    if "choretracker.app" in sys.modules:
        del sys.modules["choretracker.app"]
    app_module = importlib.import_module("choretracker.app")

    img_path = app_module.BASE_PATH / "static" / "default_profile.png"
    img_bytes = app_module.process_profile_picture(img_path.read_bytes())
    app_module.user_store.create("Bob", "bob", None, set(), profile_picture=img_bytes)

    client = TestClient(app_module.app)
    client.post("/login", data={"username": "Bob", "password": "bob"}, follow_redirects=False)
    resp = client.get("/users/Bob/profile_picture")
    assert "no-store" in resp.headers.get("cache-control", "")

