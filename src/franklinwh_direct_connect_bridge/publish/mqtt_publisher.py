"""paho-mqtt publisher with Home Assistant discovery + availability (LWT)."""

from __future__ import annotations

import json

import paho.mqtt.client as mqtt

from ..config import Settings
from . import entities


class MqttPublisher:
    def __init__(self, settings: Settings, node: str, device: dict,
                 command_handler=None, groups=None):
        self.s = settings
        self.node = node
        self.device = device
        #: Called as ``handler(key, payload)`` for an inbound control message.
        #: Runs on the paho network thread, so it must not block for long.
        self.command_handler = command_handler
        self.configs, self.state_topic, self.avail_topic = entities.discovery_configs(
            node, device, settings.mqtt_prefix, settings.ha_discovery_prefix, groups
        )
        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2, client_id=f"franklinwh-direct-connect-bridge-{node}"
        )
        if settings.mqtt_username:
            self.client.username_pw_set(settings.mqtt_username, settings.mqtt_password)
        # Last-will: mark offline if the bridge drops.
        self.client.will_set(self.avail_topic, "offline", retain=True)
        self.cmd_filter = entities.command_topic_filter(node, settings.mqtt_prefix)
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        """Subscribe on every connect, not just the first — a reconnect otherwise
        silently stops accepting commands while still publishing state, which
        looks like working."""
        if self.command_handler:
            client.subscribe(self.cmd_filter)

    def _on_message(self, client, userdata, msg):
        if not self.command_handler:
            return
        key = entities.key_from_command_topic(msg.topic)
        if not key:
            return
        try:
            payload = msg.payload.decode().strip()
        except Exception:                                        # noqa: BLE001
            return
        try:
            self.command_handler(key, payload)
        except Exception:                                        # noqa: BLE001
            # A bad command must never kill the MQTT loop.
            pass

    def start(self) -> None:
        self.client.connect(self.s.mqtt_host, self.s.mqtt_port)
        self.client.loop_start()
        self.client.publish(self.avail_topic, "online", retain=True)
        self.publish_discovery()

    def publish_discovery(self) -> None:
        """(Re-)publish the HA discovery config for every entity (retained)."""
        for topic, cfg in self.configs:
            self.client.publish(topic, json.dumps(cfg), retain=True)

    def rebuild_discovery(self, groups) -> None:
        """Re-derive the discovery set for `groups`: clear the OLD entities from HA, then
        publish the new set — so a disabled group's entities disappear from HA."""
        self.clear_discovery()
        self.configs, self.state_topic, self.avail_topic = entities.discovery_configs(
            self.node, self.device, self.s.mqtt_prefix, self.s.ha_discovery_prefix, groups)
        self.publish_discovery()

    def clear_discovery(self) -> None:
        """Remove the entities from Home Assistant by publishing an empty retained
        payload to each discovery config topic."""
        for topic, _cfg in self.configs:
            self.client.publish(topic, "", retain=True)

    def is_connected(self) -> bool:
        try:
            return bool(self.client.is_connected())
        except Exception:
            return False

    def publish_state(self, state: dict) -> None:
        # Retained so HA / new subscribers get the latest values immediately (availability
        # + LWT guard against acting on stale data if the bridge drops).
        self.client.publish(self.state_topic, json.dumps(state), retain=True)

    def publish_availability(self, online: bool) -> None:
        self.client.publish(self.avail_topic, "online" if online else "offline", retain=True)

    def stop(self) -> None:
        try:
            self.publish_availability(False)
            self.client.loop_stop()
            self.client.disconnect()
        except Exception:
            pass
