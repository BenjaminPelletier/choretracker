import importlib
import sys
from pathlib import Path
from starlette.requests import Request

# Ensure project root on path
sys.path.append(str(Path(__file__).resolve().parents[1]))


def _make_request(app, path: str = "/switch/foo") -> Request:
    scope = {
        "type": "http",
        "path": path,
        "root_path": "",
        "scheme": "http",
        "method": "GET",
        "headers": [],
        "query_string": b"",
        "app": app,
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
    }
    return Request(scope)


def test_switch_target_allowed_disallowed(tmp_path, monkeypatch):
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("CHORETRACKER_DB", str(db_file))
    monkeypatch.setenv("CHORETRACKER_SECRET_KEY", "test")
    if "choretracker.app" in sys.modules:
        del sys.modules["choretracker.app"]
    app_module = importlib.import_module("choretracker.app")

    req = _make_request(app_module.app)
    default = app_module._switch_target(req, None)

    allowed = {
        "/users": "/users",
        "relative/path": "relative/path",
        "/foo/../users": "/users",
    }
    for target, expected in allowed.items():
        assert app_module._switch_target(req, target) == expected

    disallowed = [
        "http://evil.com",
        "//evil.com",
        "foo/..//http://evil.com",
    ]
    for target in disallowed:
        assert app_module._switch_target(req, target) == default
