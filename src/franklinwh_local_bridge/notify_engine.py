"""FEAT-NOTIFY — a configurable notification TRIGGER engine on the companion-push path.

The bridge already had two notify channels: a persistent-notification ``Notifier`` (core HA)
and per-device companion push (``ha_instances.send_notification``, used by the VPP monitor +
broadcast). This adds the missing piece the Energipays bridge has: user-configurable TRIGGERS
that fire automatically on state transitions (aGate offline/online, off-grid start/end, battery
dispatch, SoC thresholds), delivered to the enabled companion devices, with a delivery LOG +
per-trigger stats.

Config lives in ``app_config['notify_triggers']`` (JSON). Evaluation is pure (transition of a
prev→cur snapshot); delivery + logging is :func:`fire`.
"""
from __future__ import annotations

import json
import logging

log = logging.getLogger(__name__)

CONFIG_KEY = "notify_triggers"

#: The trigger catalogue. `threshold` present → the UI shows a number field.
DEFAULT_TRIGGERS: dict = {
    "aGate_offline": {"enabled": True, "label": "aGate offline / online"},
    "off_grid": {"enabled": True, "label": "Off-grid started / ended"},
    "dispatch": {"enabled": True, "label": "Battery dispatch (VPP / force) started / ended"},
    "soc_low": {"enabled": False, "label": "Battery SoC drops below", "threshold": 20},
    "soc_full": {"enabled": False, "label": "Battery SoC reaches", "threshold": 100},
}


def config(store) -> dict:
    """Merged config: stored overrides on top of DEFAULT_TRIGGERS. Always well-formed."""
    cfg = {"master": True, "triggers": {k: dict(v) for k, v in DEFAULT_TRIGGERS.items()}}
    if store is None:
        return cfg
    try:
        raw = store.get_config(CONFIG_KEY)
        saved = json.loads(raw) if raw else {}
    except Exception:  # noqa: BLE001
        saved = {}
    if isinstance(saved.get("master"), bool):
        cfg["master"] = saved["master"]
    for key, sv in (saved.get("triggers") or {}).items():
        if key in cfg["triggers"] and isinstance(sv, dict):
            if isinstance(sv.get("enabled"), bool):
                cfg["triggers"][key]["enabled"] = sv["enabled"]
            if "threshold" in cfg["triggers"][key] and isinstance(sv.get("threshold"), (int, float)):
                cfg["triggers"][key]["threshold"] = sv["threshold"]
    return cfg


def set_config(store, cfg: dict) -> dict:
    """Persist a config (only master + per-trigger enabled/threshold are kept)."""
    merged = config(store)
    if isinstance(cfg.get("master"), bool):
        merged["master"] = cfg["master"]
    for key, sv in (cfg.get("triggers") or {}).items():
        if key in merged["triggers"] and isinstance(sv, dict):
            if isinstance(sv.get("enabled"), bool):
                merged["triggers"][key]["enabled"] = sv["enabled"]
            if "threshold" in merged["triggers"][key] and isinstance(sv.get("threshold"), (int, float)):
                merged["triggers"][key]["threshold"] = max(0, min(100, sv["threshold"]))
    if store is not None:
        store.set_config(CONFIG_KEY, json.dumps({
            "master": merged["master"],
            "triggers": {k: {kk: vv for kk, vv in v.items() if kk in ("enabled", "threshold")}
                         for k, v in merged["triggers"].items()},
        }))
    return merged


def _enabled(cfg: dict, key: str) -> bool:
    return cfg.get("master", True) and bool((cfg.get("triggers") or {}).get(key, {}).get("enabled"))


def evaluate(gw_label: str, summ: dict, prev: dict | None, cfg: dict) -> list[tuple]:
    """Transitions worth notifying, gated by config. Returns [(event, title, message), …].
    ``prev``/``summ`` are /api/summary snapshots; ``prev`` None on the first pass = no events."""
    if prev is None or not cfg.get("master", True):
        return []
    out: list[tuple] = []
    p, c = prev.get("power") or {}, summ.get("power") or {}
    tag = f" [{gw_label}]" if gw_label else ""

    if _enabled(cfg, "aGate_offline") and bool(prev.get("ok")) != bool(summ.get("ok")):
        out.append(("aGate_offline", "FranklinWH aGate",
                    (f"aGate is reachable again{tag}." if summ.get("ok")
                     else f"aGate is UNREACHABLE{tag} — check network / WiFi / power.")))

    if _enabled(cfg, "off_grid") and bool(p.get("off_grid")) != bool(c.get("off_grid")):
        out.append(("off_grid", "FranklinWH off-grid",
                    (f"Gateway went OFF-GRID{tag} — running on battery."
                     if c.get("off_grid") else f"Gateway is back ON-GRID{tag}.")))

    ps, cs = p.get("soc"), c.get("soc")
    if isinstance(ps, (int, float)) and isinstance(cs, (int, float)):
        if _enabled(cfg, "soc_low"):
            thr = cfg["triggers"]["soc_low"].get("threshold", 20)
            if ps >= thr > cs:
                out.append(("soc_low", "FranklinWH battery",
                            f"Battery SoC dropped below {thr}%{tag} (now {round(cs)}%)."))
        if _enabled(cfg, "soc_full"):
            thr = cfg["triggers"]["soc_full"].get("threshold", 100)
            if ps < thr <= cs:
                out.append(("soc_full", "FranklinWH battery",
                            f"Battery SoC reached {thr}%{tag} (now {round(cs)}%)."))
    return out


def fire(store, event: str, title: str, message: str, *, cfg: dict | None = None) -> int:
    """Deliver a notification to every ENABLED companion device and record each delivery in
    the log. Respects the trigger's enable flag (so callers like the VPP monitor honour the
    user's config too). Returns the number of devices that accepted it."""
    from . import ha_instances
    cfg = cfg or config(store)
    if event in (cfg.get("triggers") or {}) and not _enabled(cfg, event):
        return 0
    sent = 0
    try:
        by_id = {i["id"]: i for i in store.ha_instances()}
        devices = [d for d in store.notify_devices() if d.get("enabled")]
    except Exception as e:  # noqa: BLE001
        log.warning("notify fire: roster read failed: %s", e)
        return 0
    if not devices:                                   # nothing to deliver to — still log once
        store.log_notify(event, title=title, message=message, device="(no devices)", ok=None)
        return 0
    for d in devices:
        inst = by_id.get(d["instance_id"])
        if not inst:
            store.log_notify(event, title=title, message=message,
                             device=d.get("alias") or d["id"], ok=False)
            continue
        r = ha_instances.send_notification(inst["base_url"], inst.get("token"),
                                           d["service"], title, message)
        ok = bool(r.get("ok"))
        store.log_notify(event, title=title, message=message,
                         device=d.get("alias") or d["id"], ok=ok)
        if ok:
            sent += 1
    return sent
