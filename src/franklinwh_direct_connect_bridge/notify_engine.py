"""FEAT-NOTIFY — a configurable notification TRIGGER engine on the companion-push path.

Companion push goes through the one ``franklinwh_ha_notify`` Notifier (``actionable``), with a
template per event; the persistent-notification ``notify.Notifier`` (core HA) is separate. This adds the missing piece the Energipays bridge has: user-configurable TRIGGERS
that fire automatically on state transitions (aGate offline/online, off-grid start/end, battery
dispatch, SoC thresholds), delivered to the enabled companion devices, with a delivery LOG +
per-trigger stats.

Config lives in ``app_config['notify_triggers']`` (JSON). Evaluation is pure (transition of a
prev→cur snapshot); delivery + logging is :func:`fire`.
"""
from __future__ import annotations

import json
import logging
import re
import time

from franklinwh_ha_notify import Event

from . import actionable

log = logging.getLogger(__name__)

CONFIG_KEY = "notify_triggers"

#: The trigger catalogue. `threshold` present → the UI shows a number field.
DEFAULT_TRIGGERS: dict = {
    "aGate_offline": {"enabled": True, "label": "aGate offline / online"},
    "off_grid": {"enabled": True, "label": "Off-grid started / ended"},
    "dispatch": {"enabled": True, "label": "Battery dispatch (VPP / force) started / ended"},
    "soc_low": {"enabled": False, "label": "Battery SoC drops below", "threshold": 20},
    "soc_full": {"enabled": False, "label": "Battery SoC reaches", "threshold": 100},
    "bridge": {"enabled": True, "label": "Bridge started / restarted / stopped"},
    "health_report": {"enabled": True, "label": "Daily health report amber or red"},
    "solar_wont_fill": {"enabled": True, "label": "Today's solar won't fill the battery"},
    # #763 (owner 2026-11-19), all off until you turn them on. Each carries a button that
    # turns further ones off; `interval_min` present → the UI shows a minutes field.
    "mode_change": {"enabled": False, "label": "Operating mode changed"},
    "agate_on_4g": {"enabled": False, "label": "aGate on 4G mobile / off 4G"},
    "off_grid_reminder": {"enabled": False, "label": "Still off-grid: remind every",
                          "interval_min": 15},
    # The scheduler's own (#581). Failed is the SCHEDULE_FAILED critical alert's push.
    "schedule_failed": {"enabled": True, "label": "Run failed", "group": "Scheduler"},
    "schedule_missed": {"enabled": True, "label": "Run missed", "group": "Scheduler"},
    "schedule_aborted": {"enabled": False, "group": "Scheduler",
                         "label": "Run aborted (stopped, deferred or ended early)"},
    "schedule_no_reply": {"enabled": True, "group": "Scheduler",
                          "label": "No reply to an actionable notification"},
}

#: The off-grid reminder's interval, in minutes: at least this, at most a day.
INTERVAL_MIN, INTERVAL_MAX = 5, 1440

#: Notifications with buttons that have only a Send to setting (#281): critical alerts
#: (Acknowledge / Re-discover) and the Release / Keep question. Keyed by their event.
ASKS: dict = {
    "alert": {"label": "Critical alerts"},
    "force_running": {"label": "Release / Keep a running force"},
}


def config(store) -> dict:
    """Merged config: stored overrides on top of DEFAULT_TRIGGERS. Always well-formed."""
    cfg = {"master": True, "triggers": {k: dict(v) for k, v in DEFAULT_TRIGGERS.items()}}
    cfg["asks"] = {k: dict(v) for k, v in ASKS.items()}
    for t in (*cfg["triggers"].values(), *cfg["asks"].values()):
        t["target"] = dict(ALL)
    if store is None:
        return cfg
    for key, target in store.alert_targets().items():
        for section in ("triggers", "asks"):
            if key in cfg[section]:
                cfg[section][key]["target"] = target
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
            if "interval_min" in cfg["triggers"][key] and isinstance(sv.get("interval_min"), (int, float)):
                cfg["triggers"][key]["interval_min"] = sv["interval_min"]
            # Turned off from a notification's button (#763): when, shown in Settings.
            if isinstance(sv.get("off_by_button"), (int, float)):
                cfg["triggers"][key]["off_by_button"] = sv["off_by_button"]
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
            if "interval_min" in merged["triggers"][key] and isinstance(sv.get("interval_min"), (int, float)):
                merged["triggers"][key]["interval_min"] = int(max(INTERVAL_MIN, min(INTERVAL_MAX, sv["interval_min"])))
            if isinstance(sv.get("off_by_button"), (int, float)):
                merged["triggers"][key]["off_by_button"] = sv["off_by_button"]
            elif sv.get("enabled") is True:
                merged["triggers"][key].pop("off_by_button", None)   # on again: the note goes
    for key, sv in (cfg.get("triggers") or {}).items():
        if key in merged["triggers"] and isinstance(sv, dict) and "target" in sv:
            target = valid_target(sv["target"])
            merged["triggers"][key]["target"] = target
            if store is not None:
                store.set_alert_target(key, target)
    for key, sv in (cfg.get("asks") or {}).items():
        if key in merged["asks"] and isinstance(sv, dict) and "target" in sv:
            target = valid_target(sv["target"])
            merged["asks"][key]["target"] = target
            if store is not None:
                store.set_alert_target(key, target)
    if store is not None:
        store.set_config(CONFIG_KEY, json.dumps({
            "master": merged["master"],
            "triggers": {k: {kk: vv for kk, vv in v.items()
                             if kk in ("enabled", "threshold", "interval_min", "off_by_button")}
                         for k, v in merged["triggers"].items()},
        }))
    return merged


#: A trigger's target (#281), as agreed with the Modbus bridge: ``{"type": "all"}``,
#: ``{"type": "device", "ids": [device id, ...]}`` or ``{"type": "role", "role": ...}``.
#: Role targets (#763) go to the enabled devices linked to an account with that role; all
#: is the default.
ALL = {"type": "all"}
ROLES = ("admin", "user", "viewer")
KINDS = ("phone", "tablet", "tv", "speaker", "other")


def valid_target(target) -> dict:
    """The target as stored, or ValueError for one this bridge can't send to."""
    if not isinstance(target, dict) or target.get("type") not in ("all", "device", "role"):
        raise ValueError("a target is {type: all}, {type: device, ids: [...]} or {type: role, role: ...}")
    if target["type"] == "all":
        return dict(ALL)
    if target["type"] == "role":
        if target.get("role") not in ROLES:
            raise ValueError(f"a role target is one of {', '.join(ROLES)}")
        return {"type": "role", "role": target["role"]}
    ids = target.get("ids")
    if not isinstance(ids, list) or not ids or not all(isinstance(i, str) for i in ids):
        raise ValueError("a device target names at least one device id")
    return {"type": "device", "ids": ids}


def send_to_ids(store, key: str) -> list[str] | None:
    """Who a notification with buttons (:data:`ASKS`, or a trigger's alert such as
    ``schedule_failed``) goes to: None for all enabled
    devices, else the enabled ones among those chosen (a switched-off device stays off)."""
    cfg = config(store)
    target = (cfg["asks"].get(key) or cfg["triggers"].get(key) or {}).get("target") or ALL
    return target_ids(store, target)


def target_ids(store, target: dict) -> list[str] | None:
    """A target's enabled devices: None for all; the chosen ones; or, for a role (#763),
    the ones linked to an enabled account with that role (none linked: nobody)."""
    if not target or target.get("type") == "all":
        return None
    devices = [d for d in store.notify_devices() if d.get("enabled")]
    if target["type"] == "device":
        on = {d["id"] for d in devices}
        return [i for i in target["ids"] if i in on]
    from . import auth
    try:
        holders = {str(u["id"]) for u in auth.users(store)
                   if u["role"] == target.get("role") and u["enabled"] and not u["expired"]}
    except Exception:  # noqa: BLE001 — no accounts table yet: no one holds the role
        holders = set()
    return [d["id"] for d in devices if d.get("user_id") and str(d["user_id"]) in holders]


def kind_of(service: str, name: str = "") -> str:
    """A device's kind from its notify service and HA name, for its icon. The user can
    change it."""
    words = set(re.split(r"[^a-z0-9]+", f"{service} {name}".lower()))
    for kind, hints in (("tablet", {"tablet", "ipad", "tab"}),
                        ("tv", {"tv", "shield", "chromecast", "firestick"}),
                        ("speaker", {"speaker", "echo", "alexa", "homepod", "sonos", "nest"})):
        if words & hints:
            return kind
    return "phone" if service.removeprefix("notify.").startswith("mobile_app_") else "other"


def _enabled(cfg: dict, key: str) -> bool:
    return cfg.get("master", True) and bool((cfg.get("triggers") or {}).get(key, {}).get("enabled"))


#: The event behind each trigger whose transition has two directions. Stats and the
#: enable flag are per trigger.
TRIGGER = {"aGate_online": "aGate_offline", "on_grid": "off_grid",
           "dispatch_start": "dispatch", "dispatch_end": "dispatch", "dispatch_at_boot": "dispatch",
           "bridge_started": "bridge", "bridge_restarted": "bridge", "bridge_stopped": "bridge",
           "agate_on_wifi": "agate_on_4g"}

#: Every companion-push event and its default text (#374 P2). ``{gateway}`` is the
#: gateway's label (#361).
EVENTS = (
    Event("aGate_offline", "FranklinWH aGate",
          "aGate is UNREACHABLE [{gateway}] — check network / WiFi / power."),
    Event("aGate_online", "FranklinWH aGate", "aGate is reachable again [{gateway}]."),
    Event("off_grid", "FranklinWH off-grid",
          "Gateway went OFF-GRID [{gateway}] ({reason}) — running on battery: {metrics}.",
          ("reason", "metrics")),
    Event("on_grid", "FranklinWH off-grid", "Gateway is back ON-GRID [{gateway}]."),
    Event("soc_low", "FranklinWH battery",
          "Battery SoC dropped below {threshold}% [{gateway}] (now {soc}%).", ("threshold", "soc")),
    Event("soc_full", "FranklinWH battery",
          "Battery SoC reached {threshold}% [{gateway}] (now {soc}%).", ("threshold", "soc")),
    Event("dispatch_at_boot", "FranklinWH — VPP dispatch active at startup",
          "{gateway}: VPP (force) dispatch active at startup ({metrics}) — started externally "
          "(a utility VPP programme, the app, the Modbus bridge, or a prior run), not by this "
          "bridge. This bridge will not auto-release it; use the Release button to override if "
          "you want to clear it.", ("metrics",)),
    Event("dispatch_start", "FranklinWH — battery dispatch started (VPP)",
          "{gateway}: Battery dispatch STARTED — VPP mode active (source: {source}; {metrics}).",
          ("source", "metrics")),
    Event("dispatch_end", "FranklinWH — battery dispatch ended",
          "{gateway}: Battery dispatch ENDED{took} — VPP mode cleared, battery back to normal "
          "({metrics}).", ("took", "metrics")),
    Event("dispatch_reconcile", "FranklinWH — scheduled dispatch {action}",
          "{gateway}: {detail}", ("action", "detail")),
    Event("schedule_notify", "{title}", "{message} [{gateway}]", ("title", "message")),
    Event("broadcast", "{title}", "{message}", ("title", "message")),
    Event("schedule_missed", "FranklinWH schedule missed",
          "Schedule '{schedule}' missed its window [{gateway}]: {detail}.", ("schedule", "detail")),
    Event("schedule_aborted", "FranklinWH schedule aborted",
          "Schedule '{schedule}' did not finish [{gateway}]: {detail}.", ("schedule", "detail")),
    Event("schedule_no_reply", "FranklinWH schedule: no reply",
          "Schedule '{schedule}' got no reply [{gateway}]: {detail}.", ("schedule", "detail")),
    Event("bridge_started", "FranklinWH bridge", "Bridge started (v{version}).", ("version",)),
    Event("bridge_restarted", "FranklinWH bridge",
          "Bridge restarted (v{version}{update}) after {down} down.", ("version", "update", "down")),
    Event("bridge_stopped", "FranklinWH bridge",
          "Bridge stopping (v{version}) — no polling or notifications until it starts again.",
          ("version",)),
    Event("health_report", "{title}", "{message}", ("title", "message")),
    Event("solar_wont_fill", "FranklinWH solar",
          "Today's solar won't fill the battery [{gateway}]: about {remaining} kWh left, "
          "and it needs {needed} kWh to reach 100% (now {soc}%).", ("remaining", "needed", "soc")),
    Event("test", "FranklinWH — test", "This is a test notification from the trigger engine."),
    # #763
    Event("mode_change", "FranklinWH mode",
          "Operating mode changed [{gateway}]: {from} → {to}.", ("from", "to")),
    Event("agate_on_4g", "FranklinWH aGate",
          "aGate is using 4G mobile [{gateway}]: Wi-Fi is on standby."),
    Event("agate_on_wifi", "FranklinWH aGate", "aGate is no longer on 4G [{gateway}]."),
    Event("off_grid_reminder", "FranklinWH off-grid",
          "Still OFF-GRID [{gateway}] ({reason}) for {duration} — {metrics}.",
          ("reason", "duration", "metrics")),
)
actionable.templates().register(*EVENTS)


#: Why it went off-grid, per client._off_grid_kind: the same words as the top-bar chip. The
#: scheduler's grid.offgrid_reason uses this too.
OFF_GRID_REASON = {"simulated": "user requested", "outage": "grid outage"}

#: app_config key holding the last clean stop ({ts, version}), read once by the next start.
STOP_KEY = "bridge_last_stop"


def bridge_down(store, version: str, now: float | None = None) -> None:
    """Record a clean stop, so the next start can say it is a restart."""
    store.set_config(STOP_KEY, json.dumps({"ts": time.time() if now is None else now,
                                           "version": version}))


def bridge_up(store, version: str, now: float | None = None) -> tuple[str, dict]:
    """The start-up notification: restarted after a clean stop (how long it was down, and
    the version it came from if that changed), else started (first run, or the last run
    ended without a clean stop). The stop record is used once."""
    try:
        stop = json.loads(store.get_config(STOP_KEY) or "null")
    except ValueError:
        stop = None
    store.set_config(STOP_KEY, "")
    if not isinstance(stop, dict) or not isinstance(stop.get("ts"), (int, float)):
        return "bridge_started", {"version": version}
    down = max(0, round((time.time() if now is None else now) - stop["ts"]))
    old = stop.get("version")
    return "bridge_restarted", {
        "version": version, "down": _duration(down),
        "update": f", updated from {old}" if old and old != version else ""}


def _duration(s: int) -> str:
    h, m = divmod(s // 60, 60)
    if h:
        return f"{h} h {m} min"
    return f"{m} min {s % 60} s" if m else f"{s} s"


def _kw(w) -> str:
    return f"{w / 1000:.1f} kW"


def off_grid_metrics(power: dict, capacity_kwh: float | None) -> str:
    """SoC, stored kWh, home load and solar now, and how long the battery lasts at the
    CURRENT usage (the FranklinWH app estimates from the highest use in the past 72 h; this
    bridge has the live load). Net draw = home − solar − generator. A user-requested
    off-grid returns to the grid when the battery reaches the off-grid (reconnect) SoC, so
    it runs to that; an outage runs to empty."""
    soc, load = power.get("soc"), power.get("load_w")
    solar = power.get("solar_w") or 0
    have = isinstance(soc, (int, float))
    parts = [f"SoC {round(soc)}%" if have else None,
             f"stored {soc / 100 * capacity_kwh:.1f} kWh" if have and capacity_kwh else None,
             f"home {_kw(load)}" if isinstance(load, (int, float)) else None,
             f"solar {_kw(solar)}" if isinstance(solar, (int, float)) and solar > 0 else None]
    now = ", ".join(p for p in parts if p)
    if not have or not isinstance(load, (int, float)):
        return now or "no live readings"
    rec = power.get("offgrid_reconnect_soc")
    user = power.get("off_grid_kind") == "simulated" and isinstance(rec, (int, float))
    if user and soc <= rec:
        return f"{now} — reconnecting to the grid at {round(rec)}%"
    if not capacity_kwh:
        return f"{now} — set Battery capacity (Automation) for a runtime estimate"
    draw = load - solar - (power.get("generator_w") or 0)
    if draw <= 0:
        return f"{now} — solar is covering the home"
    usable = (soc - rec) if user else soc
    mins = round(usable / 100 * capacity_kwh * 1000 / draw * 60)
    left = f"about {mins // 60} h {mins % 60} min"
    if user:
        return f"{now} — {left} until it reconnects to the grid at {round(rec)}%"
    return f"{now} — {left} left at current usage"


def notify_on(store, settings, key: str = "off_grid") -> bool:
    """Whether a push goes out for ``key``: the Push notifications switch and the trigger."""
    return bool(getattr(settings, "ha_notify", False)) and _enabled(config(store), key)


def evaluate(summ: dict, prev: dict | None, cfg: dict,
             capacity_kwh: float | None = None) -> list[tuple[str, dict]]:
    """Transitions worth notifying, gated by config. Returns [(event, values), …].
    ``prev``/``summ`` are /api/summary snapshots; ``prev`` None on the first pass = no events.
    ``capacity_kwh``: the Battery capacity constant, for the off-grid runtime estimate."""
    if prev is None or not cfg.get("master", True):
        return []
    out: list[tuple[str, dict]] = []
    p, c = prev.get("power") or {}, summ.get("power") or {}

    if _enabled(cfg, "aGate_offline") and bool(prev.get("ok")) != bool(summ.get("ok")):
        out.append(("aGate_online" if summ.get("ok") else "aGate_offline", {}))

    if _enabled(cfg, "off_grid") and bool(p.get("off_grid")) != bool(c.get("off_grid")):
        out.append(("off_grid", {"reason": OFF_GRID_REASON.get(c.get("off_grid_kind"),
                                                                "reason unknown"),
                                 "metrics": off_grid_metrics(c, capacity_kwh)})
                   if c.get("off_grid") else ("on_grid", {}))

    # Operating mode changed (#763): both readings name a mode, and they differ.
    pm, cm = p.get("mode"), c.get("mode")
    if (_enabled(cfg, "mode_change") and prev.get("ok") and summ.get("ok")
            and pm and cm and pm != cm and "unknown" not in (str(pm).lower(), str(cm).lower())):
        out.append(("mode_change", {"from": pm, "to": cm}))

    ps, cs = p.get("soc"), c.get("soc")
    if isinstance(ps, (int, float)) and isinstance(cs, (int, float)):
        if _enabled(cfg, "soc_low"):
            thr = cfg["triggers"]["soc_low"].get("threshold", 20)
            if ps >= thr > cs:
                out.append(("soc_low", {"threshold": thr, "soc": round(cs)}))
        if _enabled(cfg, "soc_full"):
            thr = cfg["triggers"]["soc_full"].get("threshold", 100)
            if ps < thr <= cs:
                out.append(("soc_full", {"threshold": thr, "soc": round(cs)}))
    return out


def stats_by_trigger(stats: list[dict]) -> list[dict]:
    """Per-event delivery stats summed per trigger, so both directions count."""
    out: dict[str, dict] = {}
    for s in stats:
        key = TRIGGER.get(s["event"], s["event"])
        t = out.setdefault(key, {"event": key, "count": 0, "last_ts": None, "delivered": 0})
        t["count"] += s["count"]
        t["delivered"] += s["delivered"]
        t["last_ts"] = max(t["last_ts"] or 0, s["last_ts"] or 0) or None
    return sorted(out.values(), key=lambda t: -(t["last_ts"] or 0))


def fire(store, event: str, *, gateway: str | None = None, cfg: dict | None = None,
         device_ids: list[str] | None = None, logged: bool = False,
         gateway_id: str | None = None, **values) -> int:
    """Send ``event`` to every ENABLED companion device (or ``device_ids``) through the one
    Notifier, which honours the Push notifications switch (#171) and records the send.
    Respects the trigger's enable flag (so callers like the VPP monitor honour the user's
    config too). ``logged``: the caller has already written the app-log line. Returns the
    number of devices that accepted it."""
    cfg = cfg or config(store)
    trigger = TRIGGER.get(event, event)
    if trigger in (cfg.get("triggers") or {}) and not _enabled(cfg, trigger):
        return 0
    # Every notification is also a line in the app log (Logs tab), whether or not any
    # device receives it: with no companion devices it was recorded nowhere else.
    if not logged:
        _, message = actionable.templates().render(event, gateway=gateway or "", **values)
        (log.info if event == "test" else log.warning)("notify [%s]: %s", event, message)
    target = (cfg.get("triggers") or {}).get(trigger, {}).get("target") or ALL
    if device_ids is None:
        # A switched-off device stays off for its triggers too.
        device_ids = target_ids(store, target)
    from . import notify_buttons
    if event in notify_buttons.TRIGGER_BUTTONS:
        # With its button (#763); the plain one only when the ask reached no one.
        try:
            if notify_buttons.ask_trigger(store, event, trigger, device_ids, gateway=gateway,
                                          gateway_id=gateway_id, **values):
                return len(device_ids) if device_ids is not None else 1
        except Exception as e:  # noqa: BLE001 — fall back to the plain one
            log.warning("notify [%s] with its button failed: %s", event, e)
    try:
        res = actionable.send(store, event, gateway=gateway, device_ids=device_ids, **values)
    except Exception as e:  # noqa: BLE001 — a notification never breaks its caller
        log.warning("notify [%s] failed: %s", event, e)
        return 0
    return res.delivered if res else 0


# ── #763: aGate on 4G, and off-grid reminders ───────────────────────────────────
def on_alert_changes(store, changes: list[dict]) -> None:
    """The AGATE_ON_4G alert opening / resolving (it holds 5 min either way) as the
    ``agate_on_4g`` trigger's push. Other alerts are left to their own paths."""
    from .actionable import gateway_name
    for ch in changes or []:
        if ch.get("code") != "AGATE_ON_4G":
            continue
        gid = ch.get("gateway_id") or None
        fire(store, "agate_on_4g" if ch.get("change") == "opened" else "agate_on_wifi",
             gateway=gateway_name(gid), gateway_id=gid)


#: Per gateway while off-grid: {"since": first seen, "last": last reminder or the start};
#: also kept in the store (REMIND_KEY), so a restart neither restarts the count nor
#: sends twice (#618).
_REMIND: dict[str, dict] = {}
REMIND_KEY = "offgrid_reminders"
#: app_config key: the gateways whose reminders were stopped until their off-grid ends.
MUTED_KEY = "offgrid_reminders_muted"


def _muted(store) -> list[str]:
    try:
        raw = store.get_config(MUTED_KEY)
        v = json.loads(raw) if raw else []
        return [str(x) for x in v] if isinstance(v, list) else []
    except Exception:  # noqa: BLE001
        return []


def reminders_muted(store, gateway_id: str) -> bool:
    return gateway_id in _muted(store)


def mute_reminders(store, gateway_id: str, on: bool = True) -> None:
    """Stop reminders (#763) for this gateway until its off-grid ends (kept over a restart)."""
    ids = [g for g in _muted(store) if g != gateway_id] + ([gateway_id] if on else [])
    store.set_config(MUTED_KEY, json.dumps(ids))


def _saved_reminders(store) -> dict:
    try:
        raw = store.get_config(REMIND_KEY)
        v = json.loads(raw) if raw else {}
        return v if isinstance(v, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _save_reminder(store, gateway_id: str, st: dict | None) -> None:
    saved = _saved_reminders(store)
    if st is None:
        if gateway_id not in saved:
            return
        saved.pop(gateway_id)
    else:
        saved[gateway_id] = st
    try:
        store.set_config(REMIND_KEY, json.dumps(saved))
    except Exception as e:  # noqa: BLE001 — a reminder never breaks the poll
        log.debug("off-grid reminder state not saved: %s", e)


def _dur_min(s: float) -> str:
    m = int(round(s / 60))
    return f"{m} min" if m < 60 else f"{m // 60} h {m % 60} min" if m % 60 else f"{m // 60} h"


def offgrid_reminder(store, gateway_id: str, label: str, summ: dict, cfg: dict,
                     capacity_kwh: float | None, now: float) -> bool:
    """While off-grid, a reminder every ``interval_min`` (#763), saying whether you asked
    for it (user requested) or the grid went (grid outage). The off_grid event covers the
    start; a reading with no power data keeps the count; back on-grid resets it and ends a
    Stop reminders. True when one was sent."""
    power = (summ or {}).get("power") or {}
    if not summ or not summ.get("ok") or "off_grid" not in power:
        return False
    if not power.get("off_grid"):
        if _REMIND.pop(gateway_id, None) is not None or gateway_id in _saved_reminders(store):
            _save_reminder(store, gateway_id, None)
        if reminders_muted(store, gateway_id):
            mute_reminders(store, gateway_id, on=False)
        return False
    st = _REMIND.get(gateway_id)
    if st is None:
        saved = _saved_reminders(store).get(gateway_id)
        st = _REMIND[gateway_id] = (dict(saved) if isinstance(saved, dict) and "since" in saved
                                    else {"since": now, "last": now})
        _save_reminder(store, gateway_id, st)
    if not _enabled(cfg, "off_grid_reminder") or reminders_muted(store, gateway_id):
        return False
    every = 60 * float(cfg["triggers"]["off_grid_reminder"].get("interval_min") or 15)
    if now - st["last"] < every:
        return False
    st["last"] = now
    _save_reminder(store, gateway_id, st)
    fire(store, "off_grid_reminder", gateway=label, gateway_id=gateway_id, cfg=cfg,
         reason=OFF_GRID_REASON.get(power.get("off_grid_kind"), "reason unknown"),
         duration=_dur_min(now - st["since"]), metrics=off_grid_metrics(power, capacity_kwh))
    return True


def turn_off(store, trigger: str, now: float | None = None) -> None:
    """A notification's Turn off (#763): the trigger off, and when, for Settings to say."""
    set_config(store, {"triggers": {trigger: {
        "enabled": False, "off_by_button": float(now if now is not None else time.time())}}})
