import importlib
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlmodel import Session, create_engine

sys.path.append(str(Path(__file__).resolve().parents[1]))

from choretracker.users import User, UserStore, hash_pin, hash_secret, pin_context, pwd_context


@pytest.fixture
def pin_app(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORETRACKER_DB", str(tmp_path / "test.db"))
    sys.modules.pop("choretracker.app", None)
    module = importlib.import_module("choretracker.app")
    client = TestClient(module.app)
    client.post("/login", data={"username": "Admin", "password": "admin"}, follow_redirects=False)
    return module, client


def test_new_changed_and_removed_pins_and_passwords(pin_app):
    module, client = pin_app
    store = module.user_store
    admin = store.get("Admin")
    assert pin_context.identify(admin.pin_hash) == "pbkdf2_sha256"
    assert pwd_context.identify(admin.password_hash) == "bcrypt"
    assert store.create("Bob", "password", "1234", set())
    bob = store.get("Bob")
    assert pin_context.identify(bob.pin_hash) == "pbkdf2_sha256"
    assert pin_context.handler("pbkdf2_sha256").from_string(bob.pin_hash).rounds == 1_000
    assert hash_pin("1234") != bob.pin_hash  # independently salted
    assert store.verify_pin(bob, "1234")
    assert not store.verify_pin(bob, "wrong")
    assert not store.verify_pin(bob, "")
    assert store.verify("Bob", "password")
    assert store.update("Bob", "Bob", None, "5678", set())
    changed = store.get("Bob")
    assert changed.password_hash == bob.password_hash
    assert pin_context.identify(changed.pin_hash) == "pbkdf2_sha256"
    assert not store.verify_pin(changed, "1234")
    assert store.verify_pin(changed, "5678")
    assert store.update("Bob", "Bob", None, None, set(), remove_pin=True)
    assert store.verify_pin(store.get("Bob"), "")


@pytest.mark.parametrize("method", ["GET", "POST"])
def test_legacy_pin_migrates_only_after_success_and_persists(pin_app, method):
    module, client = pin_app
    store = module.user_store
    assert store.create("Bob", "password", None, set())
    legacy = hash_secret("1234")
    with Session(module.engine) as session:
        session.exec(update(User).where(User.username == "Bob").values(pin_hash=legacy))
        session.commit()
    password_hash = store.get("Bob").password_hash

    def switch(pin):
        if method == "GET":
            return client.get("/switch/Bob", params={"pin": pin}, follow_redirects=False)
        return client.post("/switch/Bob", data={"pin": pin}, follow_redirects=False)

    for wrong in ["9999", ""]:
        response = switch(wrong)
        assert response.status_code == (303 if method == "GET" else 400)
        assert store.get("Bob").pin_hash == legacy
    response = switch("1234")
    assert response.status_code == (303 if method == "GET" else 200)
    migrated = store.get("Bob")
    assert migrated.pin_hash != legacy
    assert pin_context.identify(migrated.pin_hash) == "pbkdf2_sha256"
    assert migrated.password_hash == password_hash
    # A fresh engine sees the persisted upgrade; no in-memory migration cache.
    fresh_engine = create_engine(str(module.engine.url))
    try:
        fresh_store = UserStore(fresh_engine)
        assert fresh_store.get("Bob").pin_hash == migrated.pin_hash
        assert fresh_store.verify_pin(fresh_store.get("Bob"), "1234")
        assert not fresh_store.verify_pin(fresh_store.get("Bob"), "9999")
        assert fresh_store.get("Bob").pin_hash == migrated.pin_hash
    finally:
        fresh_engine.dispose()
    assert switch("1234").status_code == (303 if method == "GET" else 200)


def test_legacy_migration_does_not_overwrite_concurrent_pin_change(pin_app):
    module, client = pin_app
    store = module.user_store
    store.create("Bob", None, None, set())
    with Session(module.engine) as session:
        session.exec(update(User).where(User.username == "Bob").values(pin_hash=hash_secret("1234")))
        session.commit()
    old_user = store.get("Bob")
    store.update("Bob", "Bob", None, "5678", set())
    new_hash = store.get("Bob").pin_hash
    assert not store.verify_pin(old_user, "1234")
    assert store.get("Bob").pin_hash == new_hash
    assert store.verify_pin(store.get("Bob"), "5678")


def test_switch_without_pin_and_missing_user(pin_app):
    module, client = pin_app
    module.user_store.create("Bob", None, None, set())
    assert client.post("/switch/Bob", data={"pin": ""}).status_code == 200
    assert client.get("/switch/Bob", follow_redirects=False).status_code == 303
    assert client.post("/switch/Missing", data={"pin": ""}).status_code == 404
