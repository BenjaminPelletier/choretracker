"""Home Assistant binary sensors, published outside the request/asyncio threads."""
from __future__ import annotations

import json
import logging
from threading import Event, Thread

import paho.mqtt.client as mqtt

from .calendar import (
    OVERDUE_LOOKBACK, CalendarEntryType, duration_for, enumerate_time_periods, responsible_for,
)
from .time_utils import end_of_day, get_now

logger = logging.getLogger(__name__)
SENSOR_TYPES = {"chores_due": "Uncompleted overdue chores or chores due today"}
REFRESH_SECONDS = 30


def users_with_due_chores(entries, completions, now):
    """Include outstanding deadlines due today or within the home page overdue window.

    Enumerate nominal periods in order, applying overrides afterwards so that a
    moved occurrence cannot hide another occurrence behind a future start.
    Midnight deadlines belong to the preceding day (the app's end-of-day value).
    """
    cutoff = end_of_day(now)
    oldest_deadline = now - OVERDUE_LOOKBACK
    due = set()
    for entry in entries:
        if entry.type != CalendarEntryType.Chore:
            continue
        for rec in entry.recurrences:
            nominal = rec.model_copy(update={"instance_specifics": {}})
            base = entry.model_copy(update={"recurrences": [nominal]})
            last_override = max(rec.instance_specifics, default=-1)
            for period in enumerate_time_periods(base):
                if period.start >= cutoff and period.instance_index > last_override:
                    break
                spec = rec.instance_specifics.get(period.instance_index)
                if spec and spec.skip:
                    continue
                start = spec.start if spec and spec.start is not None else period.start
                deadline = start + duration_for(entry, rec.id, period.instance_index)
                if not oldest_deadline <= deadline <= cutoff:
                    continue
                if (entry.id, rec.id, period.instance_index) in completions:
                    continue
                due.update(responsible_for(entry, rec.id, period.instance_index))
    return due


class SensorPublisher:
    availability_topic = "choretracker/availability"

    def __init__(self, settings, users, calendar, completions, client_factory=None):
        self.settings = settings
        self.users = users
        self.calendar = calendar
        self.completions = completions
        self.client_factory = client_factory or mqtt.Client
        self.wake = Event()
        self.stopping = Event()
        self.force = Event()
        self.thread = None
        self.client = None
        self.connection = None
        self.sent = {}
        self.status = "Not connected"

    def start(self):
        # Initialize before accepting requests to avoid racing the first settings read.
        self.settings.get_mqtt()
        self.stopping.clear()
        self.thread = Thread(target=self._run, name="home-assistant-sensors", daemon=True)
        self.thread.start()

    def notify(self):
        self.wake.set()

    def stop(self):
        self.stopping.set()
        self.wake.set()
        if self.thread:
            self.thread.join(timeout=15)

    def _run(self):
        try:
            while not self.stopping.is_set():
                self.wake.clear()
                try:
                    self.refresh()
                except Exception:
                    # Broker errors must never break chore tracking or log credentials.
                    self.status = "Unable to publish; retrying automatically"
                    logger.warning("Home Assistant sensor refresh failed; will retry")
                self.wake.wait(REFRESH_SECONDS)
        finally:
            self._disconnect()

    def _publish(self, topic, payload):
        info = self.client.publish(topic, payload, qos=1, retain=True)
        info.wait_for_publish(timeout=3)
        if info.rc != mqtt.MQTT_ERR_SUCCESS or not info.is_published():
            raise RuntimeError("MQTT publish was not acknowledged")

    def _disconnect(self):
        if self.client:
            try:
                if self.client.is_connected():
                    self._publish(self.availability_topic, "offline")
            finally:
                self.client.disconnect()
                self.client.loop_stop()
                self.client = None
                self.connection = None
                self.sent.clear()

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code == 0:
            client.subscribe("homeassistant/status", qos=1)
            self.force.set()
            self.notify()
        else:
            self.status = "Broker rejected connection; check MQTT settings"

    def _on_message(self, client, userdata, message):
        if message.topic == "homeassistant/status" and message.payload == b"online":
            self.force.set()
            self.notify()

    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        self.status = "Disconnected; retrying automatically"

    def _topics(self, kind, user_id):
        object_id = f"choretracker_{kind}_{user_id}"
        return (
            f"homeassistant/binary_sensor/{object_id}/config",
            f"choretracker/{kind}/{user_id}/state",
            object_id,
        )

    def refresh(self):
        config = self.settings.get_mqtt()
        connection = (config.host, config.port, config.username, config.password, config.tls)
        if connection != self.connection:
            # Remove retained discovery from the previous broker while reachable.
            if self.client and self.client.is_connected():
                for kind, ids in config.advertised.items():
                    for user_id in ids:
                        discovery, state, _ = self._topics(kind, user_id)
                        self._publish(discovery, "")
                        self._publish(state, "")
            self._disconnect()
            if not config.host:
                self.status = "Disabled (no broker configured)"
                return
            client = self.client_factory(
                mqtt.CallbackAPIVersion.VERSION2, client_id="choretracker",
            )
            client.on_connect = self._on_connect
            client.on_message = self._on_message
            client.on_disconnect = self._on_disconnect
            if config.username:
                client.username_pw_set(config.username, config.password)
            if config.tls:
                client.tls_set()
            client.will_set(self.availability_topic, "offline", qos=1, retain=True)
            client.reconnect_delay_set(min_delay=1, max_delay=30)
            client.connect_async(config.host, config.port, keepalive=60)
            client.loop_start()
            self.client = client
            self.connection = connection
        if not self.client or not self.client.is_connected():
            self.status = "Connecting; retrying automatically"
            return
        if self.force.is_set():
            self.force.clear()
            self.sent.clear()
        users = {user.id: user for user in self.users.list_users()}
        selected = {
            kind: sorted(set(ids) & users.keys())
            for kind, ids in config.sensors.items() if kind in SENSOR_TYPES
        }
        selected = {kind: ids for kind, ids in selected.items() if ids}
        # Save cleanup intent before publishing, including across process crashes.
        known = {
            kind: sorted(set(config.advertised.get(kind, [])) | set(selected.get(kind, [])))
            for kind in config.advertised.keys() | selected.keys()
        }
        self.settings.set_mqtt_advertised(known)
        for kind, ids in known.items():
            for user_id in set(ids) - set(selected.get(kind, [])):
                discovery, state, _ = self._topics(kind, user_id)
                self._publish(discovery, "")
                self._publish(state, "")
                self.sent.pop((kind, user_id), None)
        due = users_with_due_chores(
            self.calendar.list_entries(), self.completions.summaries(), get_now(),
        ) if selected else set()
        for kind, ids in selected.items():
            for user_id in ids:
                user = users[user_id]
                discovery, state, unique_id = self._topics(kind, user_id)
                payload = json.dumps({
                    "name": f"{user.username} has chores due",
                    "unique_id": unique_id,
                    "state_topic": state,
                    "availability_topic": self.availability_topic,
                    "payload_on": "ON",
                    "payload_off": "OFF",
                    "icon": "mdi:clipboard-check-outline",
                })
                value = "ON" if user.username in due else "OFF"
                previous = self.sent.get((kind, user_id))
                if previous is None or previous[0] != payload:
                    self._publish(discovery, payload)
                if previous is None or previous[1] != value:
                    self._publish(state, value)
                self.sent[(kind, user_id)] = (payload, value)
        self._publish(self.availability_topic, "online")
        self.settings.set_mqtt_advertised(selected)
        self.status = "Connected"
