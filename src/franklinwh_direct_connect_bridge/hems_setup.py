"""HEMS setup, opt-in (#713 step 5, #612 §5), on ``hems.loads``.

Off until the user opts in, with hems's notice. The always-on load and the high, medium and
low usage periods are pre-filled from this gateway's hourly home load (please confirm); the
user's own answers replace them. Each heavy load the user describes is checked by
``hems.loads.check`` against what this bridge can control:

- ``mode``: the operating mode (local API), always;
- ``battery_power_w`` / ``target_soc``: Battery Command, while this bridge's Modbus client is on;
- ``smart_circuits``: while the gateway has smart circuits (or their count isn't known).

Nothing here controls anything: it records the answers for the planner (#612 phase 4).
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import time

from hems import loads as hloads

log = logging.getLogger(__name__)

#: app_config: the answers, per gateway.
KEY = "hems_setup:{gw}"
#: The answers PUT accepts.
FIELDS = ("opted_in", "always_on_kw", "periods_confirmed", "loads")
#: Days of history the pre-fills look at.
HISTORY_DAYS = 28


def _answers(store, gateway_id: str) -> dict:
    try:
        v = store.get_config(KEY.format(gw=gateway_id)) if store is not None else None
        return json.loads(v) if v else {}
    except Exception:                                            # noqa: BLE001
        return {}


def save(store, gateway_id: str, body: dict) -> dict:
    """Set answers (null clears one). Unknown keys: ValueError."""
    bad = [k for k in body if k not in FIELDS]
    if bad:
        raise ValueError(f"unknown HEMS setup field(s): {', '.join(bad)}")
    if "loads" in body and body["loads"] is not None and not isinstance(body["loads"], list):
        raise ValueError("loads must be a list")
    cur = _answers(store, gateway_id)
    for k, v in body.items():
        if v is None:
            cur.pop(k, None)
        else:
            cur[k] = v
    store.set_config(KEY.format(gw=gateway_id), json.dumps(cur))
    return cur


def configured(store) -> bool:
    """Whether any gateway's HEMS setup is switched on (the setup list's Done)."""
    from . import state
    return any(_answers(store, gw.id).get("opted_in") for gw in state.gateways())


def _circuits(store, settings, gateway_id: str):
    """The gateway's smart-circuit count as the scheduler knows it (#698); None unknown."""
    from . import scheduler, state
    gw = state.get_gateway(gateway_id)
    if gw is None:
        return None
    return scheduler.accessories(store, settings, gw).get("circuits")


def capabilities(store, settings, gateway_id: str) -> list[str]:
    from . import battery_control
    caps = ["mode"]
    if battery_control.is_enabled():
        caps += ["battery_power_w", "target_soc"]
    n = _circuits(store, settings, gateway_id)
    if n is None or int(n) > 0:          # not known: nothing is taken away on a guess
        caps.append("smart_circuits")
    return caps


def view(store, settings, gateway_id: str, now: float | None = None, *,
         answers: dict | None = None) -> dict:
    """The screen: opt-in, notice, pre-fills or answers, loads with hems's checks. With
    ``answers``, those (not yet saved) are shown and checked instead of the stored ones:
    the setup wizard's Check (#736)."""
    from . import load_forecast
    now = time.time() if now is None else now
    if settings is None:
        try:
            from .config import get_settings
            settings = get_settings()
        except Exception:                                        # noqa: BLE001
            settings = None
    a = _answers(store, gateway_id) if answers is None else answers
    tz = load_forecast._zone(store)
    hist = load_forecast.hourly_load(store, gateway_id, int(now) - HISTORY_DAYS * 86400, int(now))
    if a.get("always_on_kw") is not None:
        always = {"value_kw": float(a["always_on_kw"]), "confirm": False, "basis": "yours"}
    else:
        always = hloads.always_on(hist, tz=tz)
    periods = hloads.usage_periods(hist, tz=tz)
    if a.get("periods_confirmed"):
        periods["confirm"] = False
    caps = set(capabilities(store, settings, gateway_id))
    today = dt.datetime.fromtimestamp(now, tz).date()
    loads = []
    for ld in a.get("loads") or []:
        exp = None
        try:
            exp = hloads.expected_hourly(ld, today, tz=tz)
        except Exception:                                        # noqa: BLE001 — bad times
            exp = None
        loads.append({**ld, "problems": hloads.check(ld, caps),
                      "expected_kwh_today": round(sum(exp.values()), 3) if exp else None})
    days = len({dt.datetime.fromtimestamp(h["start"], tz).date() for h in hist})
    return {"opted_in": bool(a.get("opted_in")), "notice": hloads.NOTICE,
            "always_on": always, "history_days": days, "periods": periods, "capabilities": sorted(caps),
            "loads": loads, "choices": {"device_type": [{"value": k, "label": v} for k, v
                                                        in hloads.DEVICE_TYPES.items()],
                                        "measurement": list(hloads.MEASUREMENTS),
                                        "circuit": list(hloads.CIRCUITS),
                                        "control": list(hloads.CONTROL_TYPES),
                                        "switch": list(hloads.SWITCHES),
                                        "soak_triggers": list(hloads.SOAK_TRIGGERS),
                                        "ev_fields": list(hloads.EV_FIELDS)}}
