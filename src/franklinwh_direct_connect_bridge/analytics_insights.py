"""Analytics → Explain (#588): the inputs franklinwh-ha-cloud-analytics ``insights`` needs,
from this bridge. Its samples or the cloud's totals give the period and the ones it is
compared with; the gateway, Automation and the tariff give the site. Read-only: nothing
here writes to the gateway or the cloud, and suggestions are never applied."""
from __future__ import annotations

import json
import logging

log = logging.getLogger(__name__)

#: Saved objectives, one key per gateway (owner: remembered per site).
OBJECTIVES_KEY = "insights_objectives:{gw}"
_TOTAL_KEYS = ("home", "solar", "grid_import", "grid_export", "battery_discharge",
               "battery_charge")
#: The aGate's work modes (1 TOU, 2 Self-Consumption, 3 Emergency Backup).
_WORK_MODE = {1: "tou", 2: "self", 3: "backup"}


def cloud_period(period: str) -> str:
    """The cloud period whose payload is in kWh: the Day views read the hourly one."""
    return "dayhour" if period == "day5" else period


def cloud_totals(payload: dict, days: float | None) -> dict | None:
    """A kWh payload's totals as positive numbers, plus ``days``; None when it isn't kWh
    or holds nothing."""
    if not isinstance(payload, dict) or payload.get("unit") != "kWh":
        return None
    out: dict = {}
    for s in payload.get("series") or []:
        if s.get("key") in _TOTAL_KEYS:
            vals = [abs(v) for v in s.get("values") or [] if isinstance(v, (int, float))]
            out[s["key"]] = round(sum(vals), 3) if vals else None
    if not any(v is not None for v in out.values()):
        return None
    out["days"] = days
    return out


#: Below this share of a window recorded, it isn't compared with: a week the bridge saw for
#: one day would read as a fall of six-sevenths.
MIN_COVERAGE = 0.5


def local_totals(energy: dict, days: float | None) -> dict | None:
    """``/api/metrics/energy``'s one slot as totals; None when the slot has no samples or
    less than :data:`MIN_COVERAGE` of it was recorded."""
    if (energy or {}).get("coverage") is not None and energy["coverage"] < MIN_COVERAGE:
        return None
    series = (energy or {}).get("series") or {}
    out = {k: (series.get(k) or [None])[0] for k in _TOTAL_KEYS}
    if out.get("solar") is None and out.get("home") is None:
        return None
    out["days"] = days
    return out


def tariff_summary(pricing: dict | None, month: int) -> dict | None:
    """The tariff as insights reads it: ``kind`` (flat or tou), ``buy_c`` and ``sell_c``
    (c/kWh, averaged over the day's hours for TOU) and ``peak`` (the dearest time
    period's blocks). None when there is no price."""
    from . import rate_model
    pricing = pricing or {}
    season = next((s for s in pricing.get("seasons") or []
                   if month in (s.get("months") or [])), None)
    if season and season.get("time_periods") and season.get("blocks"):
        tps = season["time_periods"]

        def price(tp, side):
            return rate_model.tier_rate((tps.get(tp) or {}).get(side), None)

        def mins(hhmm):
            h, m = (hhmm or "0:0").split(":")
            return int(h) * 60 + int(m)
        hours: dict[str, float] = {}
        for b in season["blocks"]:
            if b.get("days") not in (None, [], list(range(7))):
                continue                                   # weekday-only blocks: not averaged
            hours[b["time_period"]] = hours.get(b["time_period"], 0) + (
                mins(b.get("end")) - mins(b.get("start"))) / 60
        total = sum(hours.values())
        buys = {tp: price(tp, "buy") for tp in hours}
        if total and all(v is not None for v in buys.values()):
            sells = {tp: price(tp, "sell") for tp in hours}
            dearest = max(buys, key=buys.get)
            return {
                "kind": "tou" if len(set(buys.values())) > 1 else "flat",
                "buy_c": sum(buys[tp] * h for tp, h in hours.items()) / total * 100,
                "sell_c": (sum(sells[tp] * h for tp, h in hours.items()) / total * 100
                           if all(v is not None for v in sells.values()) else None),
                "peak": [f"{b['start']}-{b['end']}" for b in season["blocks"]
                         if b.get("time_period") == dearest] if len(set(buys.values())) > 1 else [],
            }
    rate = pricing.get("default_rate") if isinstance(pricing.get("default_rate"), dict) else {}
    buy, sell = rate_model.tier_rate(rate.get("buy"), None), rate_model.tier_rate(rate.get("sell"), None)
    if buy is None:
        return None
    return {"kind": "flat", "buy_c": round(buy * 100, 4),
            "sell_c": round(sell * 100, 4) if sell is not None else None, "peak": []}


def mode_and_reserve(gw, host) -> tuple[str | None, float | None]:
    """The gateway's mode and its reserve %, from the aGate's mode list (a read).
    (None, None) when it can't be read."""
    from . import client
    from .config import get_settings
    try:
        for m in client.cloud_reserves(get_settings(), host=host):
            if m.get("active"):
                return _WORK_MODE.get(m.get("workMode")), m.get("soc")
    except Exception as e:  # noqa: BLE001 — Explain still answers without them
        log.info("explain: mode and reserve not read: %s", e)
    return None, None


def site(store, settings, gw, host, month: int) -> dict:
    """The site as insights reads it."""
    from . import billing
    mode, reserve = mode_and_reserve(gw, host)
    try:
        from . import constants
        cap = constants.values(store).get("battery_capacity_kwh")   # Automation → capacity
    except Exception:  # noqa: BLE001
        cap = None
    cfg = None
    try:
        cfg = billing._billing_cfg(store, gw.id) if store is not None else None
    except Exception:  # noqa: BLE001
        cfg = None
    return {"mode": mode, "reserve_pct": reserve, "capacity_kwh": cap or None,
            "solar_kwp": _pv_kwp(settings),
            "tariff": tariff_summary((cfg or {}).get("pricing"), month) if cfg else None}


def _pv_kwp(settings) -> float | None:
    """The solar size: yours, else the gateways' (#583)."""
    from . import pv_size
    try:
        return pv_size.kwp(settings)
    except Exception:  # noqa: BLE001
        return None


def saved_objectives(store, gw_id: str) -> list[str]:
    try:
        raw = store.get_config(OBJECTIVES_KEY.format(gw=gw_id)) if store is not None else None
        return [o for o in (json.loads(raw) if raw else []) if isinstance(o, str)]
    except Exception:  # noqa: BLE001
        return []


def save_objectives(store, gw_id: str, objectives: list[str]) -> None:
    store.set_config(OBJECTIVES_KEY.format(gw=gw_id), json.dumps(list(objectives)))
