from datetime import datetime, timedelta
import importlib
import json
import sys
from threading import Event
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from choretracker.calendar import (
    CalendarEntry, CalendarEntryType, InstanceSpecifics, Recurrence, RecurrenceType,
)
from choretracker.mqtt import SensorPublisher, users_with_due_chores
from choretracker.time_utils import parse_datetime


def entry(start, *, duration=3600, kind=CalendarEntryType.Chore, specs=None, recurrence=RecurrenceType.OneTime):
    return CalendarEntry(
        id=42, title="Laundry", type=kind, responsible=["Alice"], managers=["Admin"],
        recurrences=[Recurrence(
            id=1, type=recurrence, first_start=parse_datetime(start),
            duration_seconds=duration, instance_specifics=specs or {},
        )],
    )


def spec(index=0, **kwargs):
    return InstanceSpecifics(entry_id=42, recurrence_id=1, instance_index=index, **kwargs)


def test_due_dates_completions_and_skips():
    now = parse_datetime("2026-11-13T00:00:15")
    old = entry("2020-01-01T00:00:00")
    today = entry("2026-11-13T22:00:00")
    tomorrow = entry("2026-11-14T01:00:00")
    assert users_with_due_chores([old], {}, now) == set()
    assert users_with_due_chores([today], {}, now) == {"Alice"}
    boundary = entry("2026-11-05T23:00:15")
    assert users_with_due_chores([boundary], {}, now) == {"Alice"}
    assert users_with_due_chores([boundary], {}, now + timedelta(seconds=1)) == set()
    old.recurrences[0].instance_specifics[0] = spec(start=now - timedelta(hours=1))
    assert users_with_due_chores([old], {}, now) == {"Alice"}
    assert users_with_due_chores([tomorrow], {}, now) == set()
    assert users_with_due_chores([today], {(42, 1, 0): object()}, now) == set()
    today.recurrences[0].instance_specifics[0] = spec(skip=True)
    assert users_with_due_chores([today], {}, now) == set()
    assert users_with_due_chores([entry("2026-11-13T10:00:00", kind=CalendarEntryType.Event)], {}, now) == set()


def test_overrides_and_out_of_order_occurrences():
    now = parse_datetime("2026-11-13T12:00:00")
    chore = entry("2026-11-06T10:00:00", recurrence=RecurrenceType.Weekly, specs={
        0: spec(start=parse_datetime("2026-12-01T10:00:00")),
        1: spec(1, responsible=["Bob"]),
    })
    assert users_with_due_chores([chore], {}, now) == {"Bob"}
    chore.recurrences[0].instance_specifics[2] = spec(2, start=now, responsible=["Carol"])
    assert users_with_due_chores([chore], {}, now) == {"Bob", "Carol"}
    chore.recurrences[0].instance_specifics[1].duration_seconds = 2 * 86400
    assert users_with_due_chores([chore], {}, now) == {"Carol"}
    chore.none_before = parse_datetime("2026-11-14T00:00:00")
    assert users_with_due_chores([chore], {}, now) == {"Carol"}
    chore.none_after = parse_datetime("2026-11-14T00:00:00")
    assert users_with_due_chores([chore], {}, now) == set()


def test_midnight_and_dst_use_configured_timezone(monkeypatch):
    monkeypatch.setenv("CHORETRACKER_TZ", "America/Los_Angeles")
    chore = entry("2026-11-01T10:00:00-08:00")
    assert users_with_due_chores([chore], {}, parse_datetime("2026-11-01T06:59:59+00:00")) == set()
    assert users_with_due_chores([chore], {}, parse_datetime("2026-11-01T07:00:15+00:00")) == {"Alice"}
    # The midnight end-of-day value is due on the preceding calendar day.
    chore = entry("2026-11-01T23:00:00-08:00")
    assert users_with_due_chores([chore], {}, parse_datetime("2026-11-01T12:00:00-08:00")) == {"Alice"}


class FakeClient:
    def __init__(self, *args, **kwargs):
        self.messages = []
        self.connected = False
        self.fail = False
        self.options = kwargs

    def username_pw_set(self, *args): self.credentials = args
    def tls_set(self): self.tls = True
    def will_set(self, *args, **kwargs): self.will = (args, kwargs)
    def reconnect_delay_set(self, **kwargs): pass
    def connect_async(self, *args, **kwargs): self.broker = args
    def loop_start(self):
        self.connected = True
        self.on_connect(self, None, None, 0, None)
    def subscribe(self, *args, **kwargs): self.subscription = args[0]
    def is_connected(self): return self.connected
    def publish(self, topic, payload, **kwargs):
        self.messages.append((topic, payload, kwargs))
        return SimpleNamespace(
            rc=0, wait_for_publish=lambda **kw: None,
            is_published=lambda: not self.fail,
        )
    def disconnect(self): self.connected = False
    def loop_stop(self): pass


@pytest.fixture
def app_module(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORETRACKER_DB", str(tmp_path / "test.db"))
    sys.modules.pop("choretracker.app", None)
    return importlib.import_module("choretracker.app")


def setup_publisher(app_module):
    a = app_module
    a.user_store.create("Alice", None, None, set())
    user = a.user_store.get("Alice")
    a.settings_store.set_mqtt(host="broker", port=8883, username="mqtt-user", password="secret", tls=True, sensors={"chores_due": [user.id]})
    publisher = SensorPublisher(a.settings_store, a.user_store, a.calendar_store, a.completion_store, FakeClient)
    return publisher, user


def test_discovery_state_dedup_reconnect_and_cleanup(app_module):
    publisher, user = setup_publisher(app_module)
    publisher.refresh()
    client = publisher.client
    discovery, state, identity = publisher._topics("chores_due", user.id)
    assert publisher._topics("chores_due", 4) == (
        "homeassistant/binary_sensor/choretracker_chores_due_4/config",
        "choretracker/chores_due/4/state",
        "choretracker_chores_due_4",
    )
    assert client.options["client_id"] == "choretracker"
    assert publisher.availability_topic == "choretracker/availability"
    messages = {topic: payload for topic, payload, _ in client.messages}
    assert json.loads(messages[discovery])["name"] == "Alice has chores due"
    assert json.loads(messages[discovery])["unique_id"] == identity
    assert messages[state] == "OFF"
    assert client.credentials == ("mqtt-user", "secret")
    assert client.broker == ("broker", 8883)
    assert client.tls and client.will[0][1] == "offline"
    assert all(options == {"qos": 1, "retain": True} for _, _, options in client.messages)
    client.messages.clear()
    publisher.refresh()
    assert [topic for topic, _, _ in client.messages] == [publisher.availability_topic]
    publisher._on_message(client, None, SimpleNamespace(topic="homeassistant/status", payload=b"online"))
    publisher.refresh()
    assert any(topic == state for topic, _, _ in client.messages)
    app_module.settings_store.set_mqtt(host="broker", port=8883, username="mqtt-user", password=None, tls=True, sensors={})
    publisher.refresh()
    assert (discovery, "", {"qos": 1, "retain": True}) in client.messages
    assert app_module.settings_store.get_mqtt().advertised == {}
    publisher._disconnect()
    assert client.messages[-1][1] == "offline"


def test_actual_chore_changes_and_stable_identity(app_module, monkeypatch):
    import choretracker.mqtt as mqtt_module

    now = parse_datetime("2026-11-13T12:00:00")
    monkeypatch.setattr(mqtt_module, "get_now", lambda: now)
    publisher, user = setup_publisher(app_module)
    chore = entry("2026-11-13T10:00:00")
    chore.id = None
    app_module.calendar_store.create(chore)
    chore = app_module.calendar_store.list_entries()[0]
    publisher.refresh()
    discovery, state, identity = publisher._topics("chores_due", user.id)
    assert any(topic == state and payload == "ON" for topic, payload, _ in publisher.client.messages)
    app_module.completion_store.create(chore.id, 1, 0, "Admin")
    publisher.refresh()
    assert publisher.sent[("chores_due", user.id)][1] == "OFF"
    app_module.completion_store.delete(chore.id, 1, 0)
    app_module.user_store.update("Alice", "Alicia", None, None, set())
    publisher.refresh()
    assert publisher._topics("chores_due", user.id)[2] == identity
    assert "Alicia has chores due" in publisher.sent[("chores_due", user.id)][0]
    assert publisher.sent[("chores_due", user.id)][1] == "ON"
    publisher._disconnect()


def test_publish_failure_retried_and_cleanup_survives_restart(app_module):
    publisher, user = setup_publisher(app_module)
    publisher.refresh()
    publisher.force.set()
    publisher.client.fail = True
    with pytest.raises(RuntimeError): publisher.refresh()
    assert publisher.sent == {}
    publisher.client.fail = False
    publisher.refresh()
    publisher._disconnect()
    app_module.settings_store.set_mqtt(host="broker", port=1883, username="", password="", tls=False, sensors={})
    replacement = SensorPublisher(app_module.settings_store, app_module.user_store, app_module.calendar_store, app_module.completion_store, FakeClient)
    replacement.refresh()
    assert any(topic.endswith('/config') and payload == "" for topic, payload, _ in replacement.client.messages)
    replacement._disconnect()


def test_admin_settings_validation_and_password_privacy(app_module):
    publisher, user = setup_publisher(app_module)
    client = TestClient(app_module.app)
    client.post('/login', data={"username": "Admin", "password": "admin"})
    page = client.get('/system')
    assert 'Home Assistant sensors' in page.text
    assert 'data-sensor="chores_due"' in page.text
    assert 'secret' not in page.text
    data = dict(host="localhost", port=1883, username="mqtt-user", password=None, tls=False, sensors={"chores_due": [user.id]})
    assert client.post('/system/mqtt', json=data).status_code == 200
    assert app_module.settings_store.get_mqtt().password == "secret"
    for changes in [dict(port=0), dict(port=65536), dict(host="mqtt://broker"), dict(host="broker:1883"), dict(sensors={"invalid": [user.id]}), dict(sensors={"chores_due": [9999]}), dict(sensors={"chores_due": [True]}), dict(host="")]:
        response = client.post('/system/mqtt', json=data | changes)
        assert response.status_code in {400, 422}
    assert app_module.settings_store.get_mqtt().host == "localhost"
    assert client.post('/system/mqtt', json=data | {"password": ""}).status_code == 200
    assert app_module.settings_store.get_mqtt().password == ""
    app_module.user_store.create("Manager", "pw", None, {"iam"})
    client.post('/login', data={"username": "Manager", "password": "pw"})
    assert client.post('/system/mqtt', json=data, follow_redirects=False).status_code == 303
    assert client.get('/system', follow_redirects=False).status_code == 303


def test_lifecycle_and_request_notifications(app_module, monkeypatch):
    refreshed = Event()
    monkeypatch.setattr(app_module.sensor_publisher, 'refresh', refreshed.set)
    with TestClient(app_module.app) as client:
        assert refreshed.wait(2)
        refreshed.clear()
        client.post('/login', data={"username": "Admin", "password": "admin"})
        assert refreshed.wait(2)
    assert not app_module.sensor_publisher.thread.is_alive()


def test_mqtt_schema_upgrade_preserves_existing_settings(app_module):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import inspect

    app_module.settings_store.set_logout_duration(7)
    cfg = Config('alembic.ini')
    command.downgrade(cfg, 'd4a3b2c1e5f6')
    assert 'mqttsettings' not in inspect(app_module.engine).get_table_names()
    command.upgrade(cfg, 'head')
    columns = {column['name'] for column in inspect(app_module.engine).get_columns('mqttsettings')}
    assert 'instance_id' not in columns
    assert app_module.settings_store.get_logout_duration() == 7
    assert app_module.user_store.get('Admin') is not None
    config = app_module.settings_store.get_mqtt()
    assert config.host == '' and config.sensors == {} and config.password == ''


def test_last_visible_recurring_chore_completion_publishes_off(app_module, monkeypatch):
    from queue import Queue
    import choretracker.mqtt as mqtt_module

    now = parse_datetime('2026-11-13T12:00:00')
    monkeypatch.setattr(app_module, 'get_now', lambda: now)
    monkeypatch.setattr(mqtt_module, 'get_now', lambda: now)
    publisher, user = setup_publisher(app_module)
    app_module.user_store.update('Alice', 'Alice', 'pw', None, {'chores.read', 'chores.complete_overdue'})
    chore = entry('2026-10-23T10:00:00', recurrence=RecurrenceType.Weekly)
    chore.id = None
    app_module.calendar_store.create(chore)
    chore = app_module.calendar_store.list_entries()[0]
    states = Queue()

    class ObservedClient(FakeClient):
        def publish(self, topic, payload, **kwargs):
            info = super().publish(topic, payload, **kwargs)
            if topic.endswith('/state'):
                states.put(payload)
            return info

    publisher.client_factory = ObservedClient
    monkeypatch.setattr(app_module, 'sensor_publisher', publisher)
    with TestClient(app_module.app) as client:
        assert states.get(timeout=3) == 'ON'
        client.post('/login', data={'username': 'Alice', 'password': 'pw'})
        response = client.post(
            f'/calendar/{chore.id}/completion',
            json={'recurrence_id': 1, 'instance_index': 3},
        )
        assert response.status_code == 200
        # Older, hidden instances remain incomplete, but the final visible one
        # is done. The request notification must promptly publish OFF.
        assert states.get(timeout=3) == 'OFF'
        response = client.post(
            f'/calendar/{chore.id}/completion/remove',
            json={'recurrence_id': 1, 'instance_index': 3},
        )
        assert response.status_code == 200
        assert states.get(timeout=3) == 'ON'
