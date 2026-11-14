import importlib
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.append(str(Path(__file__).resolve().parents[1]))


@pytest.fixture
def picture_app(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORETRACKER_DB", str(tmp_path / "test.db"))
    sys.modules.pop("choretracker.app", None)
    module = importlib.import_module("choretracker.app")
    image = (module.BASE_PATH / "static" / "default_profile.png").read_bytes()
    custom_image = module.process_profile_picture(image)
    module.user_store.create("Bob", None, None, set(), profile_picture=custom_image)
    module.user_store.create("Alice", None, None, set())
    client = TestClient(module.app)
    client.post("/login", data={"username": "Admin", "password": "admin"}, follow_redirects=False)
    return module, client


@pytest.mark.parametrize("username", ["Bob", "Alice", "Viewer"])
def test_profile_pictures_revalidate_without_retransmitting(picture_app, username):
    module, client = picture_app
    url = f"/users/{username}/profile_picture"
    first = client.get(url)
    assert first.status_code == 200
    assert first.content
    assert first.headers["cache-control"] == "private, no-cache"
    assert first.headers["content-type"] == "image/png"
    etag = first.headers["etag"]
    for validator in [etag, "W/" + etag, '"other-picture", W/' + etag, "*"]:
        response = client.get(url, headers={"If-None-Match": validator})
        assert response.status_code == 304
        assert response.content == b""
        assert response.headers["etag"] == etag
        assert response.headers["cache-control"] == "private, no-cache"
    response = client.get(url, headers={"If-None-Match": '"stale-picture"'})
    assert response.status_code == 200
    assert response.content == first.content


def test_updated_picture_invalidates_previous_etag(picture_app):
    module, client = picture_app
    for username in ["Bob", "Alice"]:
        url = f"/users/{username}/profile_picture"
        first = client.get(url)
        new_picture = b"updated-picture-" + username.encode()
        assert module.user_store.update(username, username, None, None, set(), profile_picture=new_picture)
        updated = client.get(url, headers={"If-None-Match": first.headers["etag"]})
        assert updated.status_code == 200
        assert updated.content == new_picture
        assert updated.headers["etag"] != first.headers["etag"]
        assert client.get(url, headers={"If-None-Match": updated.headers["etag"]}).status_code == 304
