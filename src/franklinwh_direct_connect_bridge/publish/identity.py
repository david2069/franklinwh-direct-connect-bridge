"""Home Assistant identity of the gateway devices: ``fwh_dc`` (#92, #252).

Before #252 each gateway's HA device was ``franklinwh_<node>``, its unique_ids
``franklinwh_<node>_<key>`` and its topics under ``franklinwh-local/``. ``franklinwh_`` is not
this bridge's own (the Modbus Bridge and FWHAI use it too), so they move to
``fwh_dc_<node>``, ``fwh_dc_<node>_<key>`` and ``fwh_dc/``. Entity ids and device names
don't change.

Moving keeps what the user has (measured on HA 2026.10.1, #252): the new entities are
published on the same device (it carries both identifiers while it moves, so its device_id
stays), the old configs are removed (QoS 1, read back), and each new entity is renamed into
the old entity's entity_id with the user's own name, icon, area, labels, aliases,
hidden/disabled state and options copied across. History and statistics follow the
entity_id. That needs Home Assistant's websocket API (the add-on has it through the
Supervisor; Docker through an HA instance with a token). Without it, or while another
bridge still publishes the old topics, the old ids are kept, the reason is shown, and the
move is tried again on the next start.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Callable

log = logging.getLogger("franklinwh_direct_connect_bridge.publish.identity")

CURRENT, LEGACY = "fwh_dc", "franklinwh"
CURRENT_PREFIX, LEGACY_PREFIX = "fwh_dc", "franklinwh-local"
#: app_config: {"mode", "reason", "at", "nodes": {node: what its move did}}.
KEY = "ha_identity"

NO_HA = ("Home Assistant's API isn't reachable, so the entities can't be moved without "
         "losing your names and renamed ids. Add your Home Assistant under Settings → "
         "Home Assistant (with a token) and restart the bridge.")
OLD_LIVE = ("Another bridge is still publishing the old topics on this broker. Stop it and "
            "restart this bridge.")
#: How long to listen for another bridge on the old topics (one poll is 10 s).
LIVE_LISTEN_S = 15.0
#: How long Home Assistant gets to add or remove the entities.
HA_WAIT_S = 30.0
#: Registry fields copied from the old entity to the new one (only what the user set).
COPY = ("name", "icon", "area_id", "labels", "aliases", "categories")

_lock = threading.Lock()
_mode: str | None = None          # decided once per process


def mode() -> str:
    return _mode or CURRENT


def set_mode(m: str | None) -> None:
    """For tests, and decide()."""
    global _mode
    _mode = m


def ns() -> str:
    return LEGACY if mode() == "legacy" else CURRENT


def prefix(settings) -> str:
    """The MQTT state/command prefix: the user's own if set, else the identity's."""
    own = (getattr(settings, "mqtt_prefix", "") or "").strip()
    if own:
        return own
    return LEGACY_PREFIX if mode() == "legacy" else CURRENT_PREFIX


def device_ident(node: str) -> str:
    return f"{ns()}_{node}"


def unique_id(node: str, key: str) -> str:
    return f"{ns()}_{node}_{key}"


def topic_node(node: str) -> str:
    """The node segment of a discovery topic. New ids sit on new topics, so a move can add
    the new configs before the old ones go."""
    return node if mode() == "legacy" else f"{CURRENT}_{node}"


def node_of(identifier: str) -> str:
    """The node of one of our device identifiers, either spelling; "" if neither."""
    for p in (f"{CURRENT}_", f"{LEGACY}_"):
        if identifier.startswith(p):
            return identifier[len(p):]
    return ""


def own_idents(node: str) -> set[str]:
    return {f"{CURRENT}_{node}", f"{LEGACY}_{node}"}


# ── state ─────────────────────────────────────────────────────────────────────────────
def load(store) -> dict:
    try:
        v = store.get_config(KEY) if store is not None else None
        return json.loads(v) if v else {}
    except Exception:                                            # noqa: BLE001
        return {}


def _save(store, st: dict) -> None:
    try:
        if store is not None:
            store.set_config(KEY, json.dumps(st))
    except Exception as e:                                       # noqa: BLE001
        log.warning("could not record the Home Assistant identity: %s", e)


def view(store) -> dict:
    """For the UI: the mode, why, and what each gateway's move did."""
    st = load(store)
    return {"mode": mode() if _mode else (st.get("mode") or None), "reason": st.get("reason"),
            "at": st.get("at"), "nodes": st.get("nodes") or {}}


# ── what is on the broker ─────────────────────────────────────────────────────────────
def legacy_topics(node: str, settings) -> list[str]:
    """Every retained topic the old identity could have for ``node``: each entity's
    discovery config in every group, and the state topics under the old prefix."""
    from . import entities
    saved = _mode
    try:
        set_mode("legacy")
        pfx = (getattr(settings, "mqtt_prefix", "") or "").strip() or LEGACY_PREFIX
        configs, state_t, avail_t = entities.discovery_configs(
            node, entities.device_info(node, node), pfx, settings.ha_discovery_prefix,
            list(entities.GROUPS))
    finally:
        set_mode(saved)
    return [t for t, _ in configs] + [state_t, avail_t] + [
        f"{pfx}/{node}/{t}" for t in ("tou", "alerts", "load_forecast")]


def legacy_nodes(settings, *, collect: Callable | None = None) -> set[str]:
    """Nodes with our old-identity discovery configs still retained on the broker."""
    from . import mqtt_scan
    dp = settings.ha_discovery_prefix or "homeassistant"
    msgs, err = (collect or mqtt_scan._collect)(settings, dp, timeout=2.5, tag="identity")
    if err:
        raise ConnectionError(err)
    out = set()
    for payload in msgs.values():
        try:
            dev = (json.loads(payload) or {}).get("device") or {}
        except Exception:                                        # noqa: BLE001
            continue
        if not mqtt_scan._is_ours(dev.get("sw_version") or ""):
            continue
        idents = [str(i) for i in dev.get("identifiers") or []]
        if any(i.startswith(f"{CURRENT}_") for i in idents):
            continue                                             # already moved
        for i in idents:
            n = i[len(f"{LEGACY}_"):] if i.startswith(f"{LEGACY}_") else ""
            if n and n != "fwh_dc_bridge":
                out.add(n)
    return out


def old_bridge_live(settings, *, listen_s: float = LIVE_LISTEN_S, factory=None) -> bool:
    """True when something publishes (not retained) on the old state topics: an older
    bridge still running against this broker."""
    from . import purge
    seen = []
    c = (factory or purge._client)(settings, "identity-live")

    def on_message(_c, _u, msg):
        if not msg.retain and msg.payload:
            seen.append(msg.topic)
    c.on_message = on_message
    c.connect(settings.mqtt_host, settings.mqtt_port)
    c.loop_start()
    try:
        pfx = (getattr(settings, "mqtt_prefix", "") or "").strip() or LEGACY_PREFIX
        c.subscribe(f"{pfx}/+/state", qos=0)
        time.sleep(listen_s)
    finally:
        c.loop_stop()
        c.disconnect()
    return bool(seen)


def ha_session(store) -> Callable[[], Any] | None:
    """A factory for a Home Assistant websocket session, or None when there is no way in:
    the Supervisor in the add-on, else the first enabled HA instance with a token."""
    import os

    from .. import ha_supervisor
    if os.environ.get("SUPERVISOR_TOKEN"):
        return lambda: ha_supervisor.WsSession(timeout=10.0)
    try:
        for inst in (store.ha_instances() if store is not None else []):
            if inst.get("enabled") and inst.get("token") and inst.get("base_url"):
                return lambda i=inst: ha_supervisor.WsSession(
                    url=i["base_url"], token=i["token"], timeout=10.0)
    except Exception:                                            # noqa: BLE001
        pass
    return None


def _ha_ok(session) -> bool:
    try:
        with session() as ws:
            user = ws.call({"type": "auth/current_user"}) or {}
        if not user.get("is_admin"):
            log.info("Home Assistant's token isn't an administrator's, so it can't rename "
                     "entities")
        return bool(user.get("is_admin"))
    except Exception as e:                                       # noqa: BLE001
        log.info("Home Assistant's API isn't usable for the identity move: %s", e)
        return False


# ── the decision, once per process ────────────────────────────────────────────────────
def decide(settings, store, *, nodes: Callable | None = None, session=None,
           live: Callable | None = None, clear: Callable | None = None) -> str:
    """The identity for this run: ``fwh_dc`` (fresh, already moved, or moving now) or
    ``legacy`` (can't move yet; the reason is recorded for the UI)."""
    with _lock:
        if _mode is not None:
            return _mode
        st = load(store)
        if st.get("mode") == CURRENT:
            set_mode(CURRENT)
            return CURRENT
        try:
            found = (nodes or legacy_nodes)(settings)
        except Exception as e:                                   # noqa: BLE001
            # No broker yet: nothing can be read or moved this run. Nothing is recorded,
            # so the next start decides again.
            log.info("Home Assistant identity: broker not readable (%s); keeping the old ids "
                     "for now", e)
            set_mode("legacy")
            return "legacy"
        now = time.time()
        if not found:
            st = {"mode": CURRENT, "reason": None, "at": now, "nodes": st.get("nodes") or {}}
        else:
            sess = session if session is not None else ha_session(store)
            if sess is None or not _ha_ok(sess):
                st = {"mode": "legacy", "reason": NO_HA, "at": now}
            elif (live or old_bridge_live)(settings):
                st = {"mode": "legacy", "reason": OLD_LIVE, "at": now}
            else:
                st = {"mode": CURRENT, "reason": None, "at": now,
                      "from": sorted(found), "nodes": st.get("nodes") or {}}
                (clear or _clear_bridge_legacy)(settings)
        _save(store, st)
        set_mode(st["mode"])
        if st["mode"] == "legacy":
            log.warning("Home Assistant identity: keeping the old ids — %s", st["reason"])
        else:
            log.info("Home Assistant identity: fwh_dc%s",
                     f" ({len(st['from'])} devices on the broker still have the old ids; each "
                     "configured gateway moves as it starts)" if st.get("from") else "")
        return st["mode"]


def _clear_bridge_legacy(settings) -> None:
    """The bridge device's own state topics under the old prefix (its configs stay: their
    ids don't change, only the topics they read)."""
    from . import entities, purge
    if (getattr(settings, "mqtt_prefix", "") or "").strip():
        return                                                   # the user's own prefix stays
    n = entities.BRIDGE_NODE
    _remove(settings, [f"{LEGACY_PREFIX}/{n}/{t}" for t in ("heartbeat", "alerts", "version")],
            purge)


def _remove(settings, topics: list[str], purge_mod) -> list[str]:
    """Empty retained, QoS 1, then read back; the topics still retained."""
    before = purge_mod.retained(settings, topics)
    if not before:
        return []
    c = purge_mod._client(settings, "identity")
    c.connect(settings.mqtt_host, settings.mqtt_port)
    c.loop_start()
    try:
        for t in sorted(before):
            c.publish(t, b"", qos=1, retain=True).wait_for_publish(timeout=5)
    finally:
        c.loop_stop()
        c.disconnect()
    return sorted(purge_mod.retained(settings, topics))


# ── one gateway's move ────────────────────────────────────────────────────────────────
def pending(node: str, settings, store=None, *,
            retained: Callable | None = None) -> tuple[bool, dict[str, bytes]]:
    """(this node still has to move, its old discovery configs still retained). Only a node
    found with old configs when the move was decided, and not moved cleanly since, has to:
    a fresh install or a finished move costs nothing. A move that left a problem runs again
    even once its old configs are gone, to finish the Home Assistant side."""
    from . import purge
    st = load(store)
    done = (st.get("nodes") or {}).get(node) or {}
    if node not in (st.get("from") or []) or (done and not done.get("problems")):
        return False, {}
    dp = settings.ha_discovery_prefix
    topics = [t for t in legacy_topics(node, settings) if t.startswith(f"{dp}/")]
    return True, (retained or purge.retained)(settings, topics)


def _registry(ws) -> list[dict]:
    return [e for e in ws.call({"type": "config/entity_registry/list"}) or []
            if e.get("platform") == "mqtt"]


def _wait(ws, test: Callable[[list[dict]], bool], wait_s: float, sleep=time.sleep) -> list[dict]:
    end = time.monotonic() + wait_s
    while True:
        reg = _registry(ws)
        if test(reg) or time.monotonic() >= end:
            return reg
        sleep(1.0)


def _row_refs(ws, row_ids: set[str]) -> list[str]:
    """Automations and scripts whose configuration names one of ``row_ids``."""
    if not row_ids:
        return []
    out = []
    for e in ws.call({"type": "config/entity_registry/list"}) or []:
        dom = e.get("entity_id", "").split(".", 1)[0]
        if e.get("platform") != dom or dom not in ("automation", "script"):
            continue
        try:
            cfg = ws.call({"type": f"{dom}/config", "entity_id": e["entity_id"]}) or {}
        except Exception:                                        # noqa: BLE001
            continue
        text = json.dumps(cfg.get("config", cfg))
        if any(r in text for r in row_ids):
            out.append(e["entity_id"])
    return sorted(out)


def move_node(settings, store, node: str, new_keys: set[str], old: dict[str, bytes],
              session, *, remove: Callable | None = None, wait_s: float = HA_WAIT_S,
              sleep=time.sleep) -> dict:
    """Move one gateway's entities to the new ids. The new configs are already published
    (with both identifiers on the device). Returns what it did; recorded per node."""
    from . import purge
    remove = remove or (lambda topics: _remove(settings, topics, purge))
    old_pfx, new_pfx = f"{LEGACY}_{node}_", f"{CURRENT}_{node}_"
    res: dict[str, Any] = {"at": time.time(), "moved": 0, "renamed": 0, "kept": 0,
                           "problems": []}
    with session() as ws:
        reg = _registry(ws)
        old_rows = {e["unique_id"][len(old_pfx):]: e for e in reg
                    if str(e.get("unique_id") or "").startswith(old_pfx)}
        want = set(old_rows) & set(new_keys)
        # What the user set on the old entities (aliases are only in the full entry).
        full = {}
        if old_rows:
            ids = [e["entity_id"] for e in old_rows.values()]
            got = ws.call({"type": "config/entity_registry/get_entries", "entity_ids": ids}) or {}
            full = {k: v for k, v in got.items() if v}
        # 1. Home Assistant has the new entities.
        reg = _wait(ws, lambda r: want <= {str(e.get("unique_id"))[len(new_pfx):] for e in r
                                           if str(e.get("unique_id") or "").startswith(new_pfx)},
                    wait_s, sleep)
        new_rows = {str(e["unique_id"])[len(new_pfx):]: e for e in reg
                    if str(e.get("unique_id") or "").startswith(new_pfx)}
        missing = want - set(new_rows)
        if missing:
            res["problems"].append(f"Home Assistant didn't add {len(missing)} new entities in "
                                   f"{int(wait_s)} s; the old ones are kept and the move is "
                                   "tried again on the next start")
            return res
        # 2. The old configs go (verified), and Home Assistant drops the old entities.
        left = remove(sorted(old))
        if left:
            res["problems"].append(f"{len(left)} old topics are still retained on the broker")
            return res
        reg = _wait(ws, lambda r: not any(str(e.get("unique_id") or "").startswith(old_pfx)
                                          for e in r), wait_s, sleep)
        # Home Assistant keeps the row of an entity it hasn't loaded (one the user disabled)
        # when its config goes: those are ours and their configs are gone, so remove them.
        for e in reg:
            if str(e.get("unique_id") or "").startswith(old_pfx):
                try:
                    ws.call({"type": "config/entity_registry/remove", "entity_id": e["entity_id"]})
                except Exception as ex:                          # noqa: BLE001
                    log.info("identity: could not remove %s: %s", e["entity_id"], ex)
        reg = _registry(ws)
        still = {str(e["unique_id"])[len(old_pfx):] for e in reg
                 if str(e.get("unique_id") or "").startswith(old_pfx)}
        res["moved"] = len(old_rows) - len(still)
        # 3. Each new entity takes the old entity_id and what the user set.
        for key in sorted(want - still):
            o, n = old_rows[key], new_rows[key]
            f = full.get(o["entity_id"]) or o
            upd: dict[str, Any] = {"type": "config/entity_registry/update",
                                   "entity_id": n["entity_id"]}
            if n["entity_id"] != o["entity_id"]:
                upd["new_entity_id"] = o["entity_id"]
            copy = [k for k in COPY if f.get(k) not in (None, [], "")]
            for k in copy:
                upd[k] = f[k]
            # What the user set (aliases [None] is HA's default: the entity's own name).
            kept = [k for k in copy if not (k == "aliases" and not [a for a in f[k] if a])]
            for k in ("hidden_by", "disabled_by"):
                if f.get(k) == "user":
                    upd[k] = "user"
                    kept.append(k)
            try:
                ws.call(upd)
                eid = o["entity_id"]
                for dom, opts in (f.get("options") or {}).items():
                    if opts and dom not in ("mqtt", "cloud.alexa", "cloud.google_assistant"):
                        ws.call({"type": "config/entity_registry/update", "entity_id": eid,
                                 "options_domain": dom, "options": opts})
                        if opts != (n.get("options") or {}).get(dom):
                            kept.append(f"options.{dom}")
                res["renamed"] += 1 if "new_entity_id" in upd else 0
                res["kept"] += 1 if kept else 0
            except Exception as e:                               # noqa: BLE001
                res["problems"].append(f"{o['entity_id']}: {e}")
        for key in sorted(still & want):
            res["problems"].append(f"{old_rows[key]['entity_id']}: Home Assistant kept the old "
                                   "entity, so the new one has its own id")
        # Automations and scripts that pick a moved entity through its device (a device
        # trigger, condition or action) name it by its registry row, which is new now:
        # Home Assistant disables them on the next reload (measured, G1). Named here.
        refs = _row_refs(ws, {o["id"] for o in old_rows.values() if o.get("id")})
        if refs:
            res["refs"] = refs
            # A note, not a problem: moving again wouldn't change it.
            res.setdefault("notes", []).append(
                "These pick a moved entity through its device, and Home Assistant will turn "
                "them off on the next restart; open each and choose the entity again: "
                + ", ".join(refs))
    # 4. The old state topics.
    pfx = (getattr(settings, "mqtt_prefix", "") or "").strip()
    if not pfx:
        remove([t for t in legacy_topics(node, settings) if t.startswith(f"{LEGACY_PREFIX}/")])
    return res


def record(store, node: str, res: dict) -> None:
    with _lock:
        st = load(store)
        prev = (st.get("nodes") or {}).get(node) or {}
        if prev.get("problems"):                         # a finished retry adds to the first run
            res = {**res, **{k: int(prev.get(k) or 0) + int(res.get(k) or 0)
                             for k in ("moved", "renamed", "kept")}}
        st.setdefault("nodes", {})[node] = res
        _save(store, st)
    msg = (f"Home Assistant identity: {node} moved to fwh_dc — {res['moved']} entities, "
           f"{res['renamed']} renamed back to their ids, {res['kept']} with your settings kept")
    for n in res.get("notes") or []:
        log.warning("Home Assistant identity: %s", n)
    if res["problems"]:
        log.warning("%s; problems: %s", msg, "; ".join(res["problems"]))
    else:
        log.info(msg)
