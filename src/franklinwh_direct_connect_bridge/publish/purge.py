"""Verified removal of everything this bridge published to Home Assistant for one gateway (#119).

"Clear HA" sent an empty retained payload to the *current* discovery topics only, at QoS 0,
and never checked. State and availability stayed retained on the broker, entities of a
group switched off earlier were never removed, and nothing said whether it worked.

This removes **every** topic the bridge can publish for a node — the discovery config of
each entity in every group, plus the state and availability topics — at QoS 1, then reads
the broker back and reports what is still retained. Nothing is removed that this bridge
does not own: the topic list is derived from our own entity table and node, never from a
broker wildcard.
"""
from __future__ import annotations

import time
from typing import Any, Callable

import paho.mqtt.client as mqtt

from ..config import Settings
from . import entities


def topics_for(node: str, settings: Settings) -> list[str]:
    """Every retained topic this bridge can publish for ``node``, whatever groups are on."""
    configs, state_topic, avail_topic = entities.discovery_configs(
        node, entities.device_info(node, node), settings.mqtt_prefix,
        settings.ha_discovery_prefix, list(entities.GROUPS))
    return [t for t, _ in configs] + [state_topic, avail_topic]


def _client(settings: Settings, suffix: str) -> mqtt.Client:
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                    client_id=f"franklinwh-direct-connect-bridge-{suffix}-{int(time.time())}")
    if settings.mqtt_username:
        c.username_pw_set(settings.mqtt_username, settings.mqtt_password)
    return c


def retained(settings: Settings, topics: list[str], wait_s: float = 2.0,
             factory: Callable[[Settings, str], Any] = _client) -> dict[str, bytes]:
    """Read back which of ``topics`` still hold a non-empty retained message."""
    found: dict[str, bytes] = {}
    want = set(topics)
    c = factory(settings, "verify")

    def on_message(_c, _u, msg):
        if msg.topic in want and msg.retain and msg.payload:
            found[msg.topic] = msg.payload

    c.on_message = on_message
    c.connect(settings.mqtt_host, settings.mqtt_port)
    c.loop_start()
    try:
        for t in topics:
            c.subscribe(t, qos=1)
        time.sleep(wait_s)             # retained messages arrive right after SUBACK
    finally:
        c.loop_stop()
        c.disconnect()
    return found


def purge(settings: Settings, node: str, *, dry_run: bool = False, wait_s: float = 2.0,
          factory: Callable[[Settings, str], Any] = _client) -> dict[str, Any]:
    """Remove this node's retained topics and verify. Returns counts and what is left."""
    topics = topics_for(node, settings)
    before = retained(settings, topics, wait_s, factory)
    if dry_run:
        return {"ok": True, "dry_run": True, "node": node, "topics": len(topics),
                "would_remove": sorted(before)}
    c = factory(settings, "purge")
    c.connect(settings.mqtt_host, settings.mqtt_port)
    c.loop_start()
    try:
        for t in sorted(before):
            c.publish(t, b"", qos=1, retain=True).wait_for_publish(timeout=5)
    finally:
        c.loop_stop()
        c.disconnect()
    left = retained(settings, topics, wait_s, factory)
    return {"ok": not left, "dry_run": False, "node": node, "found": len(before),
            "removed": len(before) - len(left), "left": sorted(left)}
