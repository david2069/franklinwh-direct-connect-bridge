"""paho-mqtt publisher with Home Assistant discovery + availability (LWT)."""

from __future__ import annotations

import json
import logging

import paho.mqtt.client as mqtt

from ..config import Settings
from . import entities, identity

log = logging.getLogger("franklinwh_direct_connect_bridge.publish.mqtt_publisher")


class MqttPublisher:
    def __init__(self, settings: Settings, node: str, device: dict,
                 command_handler=None, groups=None, skip=frozenset()):
        self.s = settings
        self.skip = frozenset(skip)       # entity keys this gateway has no source for
        self.groups = groups              # the publish groups switched on
        self.node = node
        self.device = device
        #: Called as ``handler(key, payload)`` for an inbound control message.
        #: Runs on the paho network thread, so it must not block for long.
        self.command_handler = command_handler
        #: Commands are obeyed only while the Controls group is published (#399): with it
        #: off the entities leave HA, and the topics must stop working too.
        self.controls_on = "controls" in entities._enabled(groups)
        self.configs, self.state_topic, self.avail_topic = entities.discovery_configs(
            node, device, identity.prefix(settings), settings.ha_discovery_prefix, groups,
            skip=self.skip,
        )
        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2, client_id=f"franklinwh-direct-connect-bridge-{node}"
        )
        if settings.mqtt_username:
            self.client.username_pw_set(settings.mqtt_username, settings.mqtt_password)
        # Last-will: mark offline if the bridge drops.
        self.client.will_set(self.avail_topic, "offline", retain=True)
        self.cmd_filter = entities.command_topic_filter(node, identity.prefix(settings))
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        """Subscribe on every connect, not just the first — a reconnect otherwise
        silently stops accepting commands while still publishing state, which
        looks like working."""
        if self.command_handler and self.controls_on:
            client.subscribe(self.cmd_filter)

    def _on_message(self, client, userdata, msg):
        if not self.command_handler:
            return
        key = entities.key_from_command_topic(msg.topic)
        if not key:
            return
        if not self.controls_on:
            # In flight when the group went off, or sent before the unsubscribe landed.
            log.warning("[%s] control '%s' refused: the Controls group is off", self.node, key)
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
        self.groups = groups
        self.configs, self.state_topic, self.avail_topic = entities.discovery_configs(
            self.node, self.device, identity.prefix(self.s), self.s.ha_discovery_prefix, groups,
            skip=self.skip)
        self.publish_discovery()
        was, self.controls_on = self.controls_on, "controls" in entities._enabled(groups)
        if self.command_handler and self.controls_on != was:
            if self.controls_on:
                self.client.subscribe(self.cmd_filter)
            else:
                self.client.unsubscribe(self.cmd_filter)

    def set_skip(self, skip) -> None:
        """Follow a source turning on or off (#711): publish the entities that now have a
        source and clear (empty retained config) those that lost theirs, so HA drops them
        rather than showing them unavailable. Nothing is sent when nothing changed."""
        skip = frozenset(skip)
        if skip == self.skip:
            return
        self.skip = skip
        old = dict(self.configs)
        self.configs, self.state_topic, self.avail_topic = entities.discovery_configs(
            self.node, self.device, identity.prefix(self.s), self.s.ha_discovery_prefix,
            self.groups, skip=self.skip)
        new = dict(self.configs)
        for topic in old.keys() - new.keys():
            self.client.publish(topic, "", retain=True)
        for topic in new.keys() - old.keys():
            self.client.publish(topic, json.dumps(new[topic]), retain=True)

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

    def publish_alerts(self, payload: dict) -> None:
        """Bridge problem (#271). Retained, so HA has it at once after a restart."""
        self.client.publish(entities.alerts_topic(self.node, identity.prefix(self.s)),
                            json.dumps(payload), retain=True)

    def publish_load_forecast(self, payload: dict) -> None:
        """Load Forecast (#713): this hour's kW and HAEO's series. Retained."""
        self.client.publish(entities.load_forecast_topic(self.node, identity.prefix(self.s)),
                            json.dumps(payload), retain=True)

    def publish_tou(self, payload: dict) -> None:
        """The TOU entities (#421): worked out from the copy of the schedule. Retained."""
        self.client.publish(entities.tou_topic(self.node, identity.prefix(self.s)),
                            json.dumps(payload), retain=True)

    def publish_availability(self, online: bool) -> None:
        self.client.publish(self.avail_topic, "online" if online else "offline", retain=True)

    def stop(self) -> None:
        try:
            self.publish_availability(False)
            self.client.loop_stop()
            self.client.disconnect()
        except Exception:
            pass


class BridgeHeartbeat:
    """The bridge's own MQTT connection, for the single "Bridge heartbeat" (#271, §11).

    Separate from every gateway's publisher on purpose: the heartbeat proves the bridge
    process and its alert monitor are alive, so it must not stop because a gateway is
    unreachable, deferred or switched off. The discovery config is (re)published on
    every connect, so a broker that lost its retained messages gets it back."""

    def __init__(self, settings: Settings):
        self.s = settings
        try:                     # the prefix depends on the identity (#252)
            from ..db import get_store
            identity.decide(settings, get_store(settings))
        except Exception as e:  # noqa: BLE001
            log.debug("identity not decided: %s", e)
        self.config_topic, self.config = entities.heartbeat_config(
            identity.prefix(settings), settings.ha_discovery_prefix)
        self.problem_topic, self.problem_config = entities.bridge_problem_config(
            identity.prefix(settings), settings.ha_discovery_prefix)
        self.version_topic, self.version_config = entities.bridge_version_config(
            identity.prefix(settings), settings.ha_discovery_prefix)
        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"franklinwh-direct-connect-bridge-{entities.BRIDGE_NODE}")
        if settings.mqtt_username:
            self.client.username_pw_set(settings.mqtt_username, settings.mqtt_password)
        self.client.on_connect = self._on_connect

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        client.publish(self.config_topic, json.dumps(self.config), retain=True)
        client.publish(self.problem_topic, json.dumps(self.problem_config), retain=True)
        client.publish(self.version_topic, json.dumps(self.version_config), retain=True)

    def start(self) -> None:
        self.client.connect(self.s.mqtt_host, self.s.mqtt_port)
        self.client.loop_start()

    def is_connected(self) -> bool:
        try:
            return bool(self.client.is_connected())
        except Exception:
            return False

    def beat(self, now: float) -> None:
        # Retained: if the bridge stops, the last heartbeat stays readable, and visibly old.
        self.client.publish(entities.heartbeat_topic(identity.prefix(self.s)),
                            entities.heartbeat_payload(now), retain=True)

    def publish_problem(self, payload: dict) -> None:
        """The bridge-level "Bridge problem" (#286). Retained, like the per-gateway one."""
        self.client.publish(entities.alerts_topic(entities.BRIDGE_NODE, identity.prefix(self.s)),
                            json.dumps(payload), retain=True)

    def publish_version(self, payload: dict) -> None:
        """The bridge-level "Bridge Version" (#706). Retained, so HA has it after a restart."""
        self.client.publish(entities.version_topic(identity.prefix(self.s)),
                            json.dumps(payload), retain=True)

    def stop(self) -> None:
        try:
            self.client.loop_stop()
            self.client.disconnect()
        except Exception:
            pass
