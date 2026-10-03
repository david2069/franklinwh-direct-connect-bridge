"""Scan the MQTT broker for FranklinWH HA-discovery configs (FEAT-SETUP-WIZARD).

The Local Bridge shares a broker; the Modbus bridge and FWHAI publish under the SAME
``franklinwh_<id>_<key>`` namespace + ``homeassistant/`` discovery prefix. On a shared broker
their device identifiers can merge (last-writer-wins metadata) and, if two producers ever used
the same node id, their unique_ids/topics would collide outright.

This connects, collects the RETAINED discovery configs matching ``franklinwh_``, groups them by
device identifier, and reports each distinct producer (name + firmware + entity count) plus
whether any is NOT this bridge — so the setup wizard can warn and offer the namespace fix.
Read-only; never raises past a status dict.
"""
from __future__ import annotations

import json
import time
from typing import Any


def scan_conflicts(settings, own_node: str, *, timeout: float = 2.5) -> dict[str, Any]:
    """Collect FranklinWH discovery configs on the broker, grouped by device. Returns
    {ok, own_node, discovery_prefix, producers:[{identifier,name,sw_version,entities,is_self}],
    foreign_count, collision}. ``collision`` is True when a NON-self producer shares this
    bridge's device identifier (a genuine last-writer-wins merge)."""
    import paho.mqtt.client as mqtt

    prefix = settings.ha_discovery_prefix or "homeassistant"
    own_ident = f"franklinwh_{own_node}"
    msgs: dict[str, bytes] = {}

    def on_connect(client, userdata, flags, rc, properties=None):
        # HA discovery configs live at <prefix>/<component>/[<node>/]<object>/config
        client.subscribe(f"{prefix}/+/+/config")
        client.subscribe(f"{prefix}/+/+/+/config")

    def on_message(client, userdata, msg):
        try:
            if b"franklinwh" in msg.payload.lower() or "franklinwh" in msg.topic.lower():
                msgs[msg.topic] = msg.payload
        except Exception:  # pragma: no cover
            pass

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                         client_id=f"franklinwh-local-scan-{own_node}")
    if settings.mqtt_username:
        client.username_pw_set(settings.mqtt_username, settings.mqtt_password)
    client.on_connect = on_connect
    client.on_message = on_message
    try:
        client.connect(settings.mqtt_host, settings.mqtt_port)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"cannot reach broker {settings.mqtt_host}:{settings.mqtt_port} — {e}"}
    client.loop_start()
    time.sleep(max(0.5, min(timeout, 8.0)))
    client.loop_stop()
    try:
        client.disconnect()
    except Exception:  # pragma: no cover
        pass

    return analyze(msgs, own_ident, prefix, own_node)


def analyze(msgs: dict[str, bytes], own_ident: str, prefix: str, own_node: str) -> dict[str, Any]:
    """Group retained discovery configs by device identifier → producer list + verdict. Pure
    (no network) so it is unit-testable. ``collision`` is True when a NON-self producer shares
    this bridge's device identifier; ``foreign_count`` counts distinct producers that are not
    this bridge (the duplicate-HA-device case on a shared broker)."""
    devices: dict[str, dict] = {}
    for _topic, payload in msgs.items():
        try:
            cfg = json.loads(payload)
        except Exception:  # noqa: BLE001
            continue
        dev = cfg.get("device") or {}
        idents = dev.get("identifiers") or []
        ident = (idents[0] if idents else None) or dev.get("name") or "?"
        d = devices.setdefault(ident, {
            "identifier": ident, "name": dev.get("name"),
            "sw_version": dev.get("sw_version"), "model": dev.get("model"),
            "manufacturer": dev.get("manufacturer"), "entities": 0})
        d["entities"] += 1
        for k in ("name", "sw_version", "model"):  # keep the richest metadata seen
            if not d.get(k) and dev.get(k):
                d[k] = dev.get(k)

    producers, collision = [], False
    for ident, d in devices.items():
        is_self = (ident == own_ident) and ("Local Bridge" in (d.get("sw_version") or ""))
        if ident == own_ident and not is_self:      # a non-self producer under OUR identifier
            collision = True
        d["is_self"] = is_self
        producers.append(d)
    producers.sort(key=lambda x: (not x["is_self"], -x["entities"]))
    foreign = [p for p in producers if not p["is_self"]]
    return {"ok": True, "own_node": own_node, "own_identifier": own_ident,
            "discovery_prefix": prefix, "producers": producers,
            "foreign_count": len(foreign), "collision": collision}
