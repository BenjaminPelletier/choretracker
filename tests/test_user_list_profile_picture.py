import importlib
import sys
from pathlib import Path
import re

from fastapi.testclient import TestClient

# Ensure project root on path
sys.path.append(str(Path(__file__).resolve().parents[1]))


def test_user_list_includes_profile_pictures(tmp_path, monkeypatch):
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("CHORETRACKER_DB", str(db_file))
    if "choretracker.app" in sys.modules:
        del sys.modules["choretracker.app"]
    app_module = importlib.import_module("choretracker.app")

    client = TestClient(app_module.app)
    client.post("/login", data={"username": "Admin", "password": "admin"}, follow_redirects=False)

    # Create a user with only iam permission
    app_module.user_store.create("Manager", None, None, {"iam"})

    resp = client.get("/users")
    text = resp.text

    assert "/users/Admin/profile_picture" in text
    assert "/users/Manager/profile_picture" in text
    assert "(admin)" in text
    assert "(iam)" not in text

    # Profile picture appears before username for Manager
    assert re.search(r"<li>\s*<img src=\"[^\"]*/users/Manager/profile_picture\"[^>]*>\s*Manager", text)
