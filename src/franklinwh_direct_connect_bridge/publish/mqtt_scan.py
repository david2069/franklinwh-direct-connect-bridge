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


def _collect(settings, prefix: str, *, timeout: float, tag: str):
    """Sniff the broker for retained FranklinWH discovery configs.
    Returns ``(msgs, error)`` — ``msgs`` maps topic -> raw payload. Never raises."""
    import paho.mqtt.client as mqtt

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

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"franklinwh-local-{tag}")
    if settings.mqtt_username:
        client.username_pw_set(settings.mqtt_username, settings.mqtt_password)
    client.on_connect = on_connect
    client.on_message = on_message
    try:
        client.connect(settings.mqtt_host, settings.mqtt_port)
    except Exception as e:  # noqa: BLE001
        return msgs, f"cannot reach broker {settings.mqtt_host}:{settings.mqtt_port} - {e}"
    client.loop_start()
    time.sleep(max(0.5, min(timeout, 8.0)))
    client.loop_stop()
    try:
        client.disconnect()
    except Exception:  # pragma: no cover
        pass
    return msgs, None


def scan_conflicts(settings, own_node: str, *, timeout: float = 2.5) -> dict[str, Any]:
    """Collect FranklinWH discovery configs on the broker, grouped by device. Returns
    {ok, own_node, discovery_prefix, producers:[{identifier,name,sw_version,entities,is_self}],
    foreign_count, collision}. ``collision`` is True when a NON-self producer shares this
    bridge's device identifier (a genuine last-writer-wins merge)."""
    prefix = settings.ha_discovery_prefix or "homeassistant"
    msgs, err = _collect(settings, prefix, timeout=timeout, tag=f"scan-{own_node}")
    if err:
        return {"ok": False, "error": err}
    return analyze(msgs, f"franklinwh_{own_node}", prefix, own_node)


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


# ── orphaned discovery configs ────────────────────────────────────────────────
# A discovery config is published RETAINED, so the broker keeps handing it to Home
# Assistant forever. If this bridge stops publishing a node — the gateway's serial
# changed, a mock gateway was torn down, or discovery was once published under the
# old "agate" fallback — HA keeps re-creating those entities on every restart and
# there is nothing that expires them. They have to be cleared explicitly, by
# publishing an empty payload to the same topic.
#
# The danger is the opposite mistake: this broker is shared with the Modbus bridge
# and FWHAI, which publish into the SAME `franklinwh_*` namespace. Clearing one of
# their topics would silently delete a working integration's entities. So ownership
# is decided by the `sw_version` prefix that device_info() stamps, the same signal
# `is_self` uses above, and anything not provably ours is reported and left alone.

OWN_SW_PREFIX = "Local Bridge"


def find_orphans(msgs: dict[str, bytes], live_nodes, prefix: str) -> dict[str, Any]:
    """Classify retained discovery configs into ours-live / ours-orphaned / foreign.

    Pure (no network) so the classification is unit-testable against a captured
    broker dump. ``live_nodes`` is the set of node ids currently published by this
    bridge — anything of ours outside it is an orphan.

    Returns {ok, discovery_prefix, live_nodes, orphans:[{node, entities, sw_version,
    topics}], live:[...], foreign:[...], orphan_topics, counts}.
    """
    live = {str(n).lower() for n in (live_nodes or []) if n}
    groups: dict[str, dict] = {}
    for topic, payload in msgs.items():
        try:
            cfg = json.loads(payload)
        except Exception:  # noqa: BLE001 — a non-JSON retained message is not ours
            continue
        if not payload.strip():          # already-cleared topic; nothing to do
            continue
        dev = cfg.get("device") or {}
        idents = dev.get("identifiers") or []
        ident = (idents[0] if idents else None) or ""
        sw = dev.get("sw_version") or ""
        # The node comes from the device identifier, not the topic: the identifier is
        # what HA keys the device on, and the 3-segment topic form carries no node.
        node = ident[len("franklinwh_"):] if ident.startswith("franklinwh_") else ""
        ours = sw.startswith(OWN_SW_PREFIX)
        key = ident or topic
        g = groups.setdefault(key, {
            "identifier": ident, "node": node, "name": dev.get("name"),
            "sw_version": sw, "ours": ours, "entities": 0, "topics": []})
        g["entities"] += 1
        g["topics"].append(topic)

    ours_live, ours_orphan, foreign = [], [], []
    for g in groups.values():
        g["topics"].sort()
        if not g["ours"]:
            foreign.append(g)
        elif g["node"] and g["node"].lower() in live:
            ours_live.append(g)
        else:
            ours_orphan.append(g)
    for lst in (ours_live, ours_orphan, foreign):
        lst.sort(key=lambda x: (-x["entities"], x["identifier"]))

    orphan_topics = [t for g in ours_orphan for t in g["topics"]]
    return {
        "ok": True,
        "discovery_prefix": prefix,
        "live_nodes": sorted(live),
        "orphans": ours_orphan,
        "live": ours_live,
        "foreign": foreign,
        "orphan_topics": orphan_topics,
        "counts": {
            "orphaned": len(orphan_topics),
            "orphaned_devices": len(ours_orphan),
            "live": sum(g["entities"] for g in ours_live),
            "foreign": sum(g["entities"] for g in foreign),
            "foreign_devices": len(foreign),
        },
    }


def scan_orphans(settings, live_nodes, *, timeout: float = 2.5) -> dict[str, Any]:
    """Read-only: what a purge WOULD clear. Publishes nothing."""
    prefix = settings.ha_discovery_prefix or "homeassistant"
    msgs, err = _collect(settings, prefix, timeout=timeout, tag="orphan-scan")
    if err:
        return {"ok": False, "error": err}
    out = find_orphans(msgs, live_nodes, prefix)
    out["dry_run"] = True
    return out


def purge_orphans(settings, live_nodes, *, timeout: float = 2.5,
                  expect: int | None = None) -> dict[str, Any]:
    """Clear this bridge's orphaned discovery configs by publishing an empty retained
    payload to each. Re-scans first and acts on that fresh result, so a stale
    dry-run list can never be replayed against a changed broker.

    ``expect`` is the orphan count the caller was shown. If the fresh scan disagrees
    the purge is refused — the operator confirmed a different set than is now there.
    """
    import paho.mqtt.client as mqtt

    plan = scan_orphans(settings, live_nodes, timeout=timeout)
    if not plan.get("ok"):
        return plan
    topics = plan["orphan_topics"]
    if expect is not None and expect != len(topics):
        return {"ok": False, "error": (f"broker changed since the dry run: expected {expect} "
                                       f"orphaned topics, found {len(topics)}. Re-run the scan."),
                "counts": plan["counts"]}
    if not topics:
        return {"ok": True, "cleared": 0, "detail": "nothing to clear", "counts": plan["counts"]}

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="franklinwh-local-purge")
    if settings.mqtt_username:
        client.username_pw_set(settings.mqtt_username, settings.mqtt_password)
    try:
        client.connect(settings.mqtt_host, settings.mqtt_port)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"cannot reach broker — {e}"}
    client.loop_start()
    cleared, failed = 0, []
    for t in topics:
        try:
            info = client.publish(t, payload=b"", qos=1, retain=True)
            info.wait_for_publish(timeout=5)
            cleared += 1
        except Exception as e:  # noqa: BLE001
            failed.append({"topic": t, "error": str(e)})
    client.loop_stop()
    try:
        client.disconnect()
    except Exception:  # pragma: no cover
        pass
    return {"ok": not failed, "cleared": cleared, "failed": failed,
            "devices": [{"node": g["node"], "entities": g["entities"]} for g in plan["orphans"]],
            "counts": plan["counts"],
            "detail": f"cleared {cleared} retained discovery topics across "
                      f"{len(plan['orphans'])} orphaned device(s)"}
