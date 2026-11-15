"""The Billing & Utilities page (#613, #629): which meter, what is still to set up, the
meter's plans as OUTUS plans, and the open period's bill.

The setup steps (site → meter → plan → tariffs) come from hems, the OUTUS engine, so the
page, Explain and the scheduler's messages all say the same thing. A bridge tariff becomes
an OUTUS plan through its tariff-profile export, which hems imports.
"""
from __future__ import annotations

import copy
import datetime as dt
import threading
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from hems import billing as hbilling, ledger, periods, profile_v1, setup

from . import setup_wizard, tariff_io


def _meters(store) -> list[dict[str, Any]]:
    """Every meter with its site and the enabled gateways that feed it (default first)."""
    gws = [g for g in store.gateways() if g.get("enabled", 1)]
    gws.sort(key=lambda g: not g.get("is_default"))
    out = []
    for m in store.meters():
        out.append({"id": m["id"], "name": m.get("name") or "Meter", "site_id": m.get("site_id"),
                    "is_default": bool(m.get("is_default")),
                    "gateway_ids": [g["id"] for g in gws if g.get("meter_id") == m["id"]]})
    out.sort(key=lambda m: not m["is_default"])
    return out


def outus_plan(store, tariff_id: str) -> dict[str, Any] | None:
    """One bridge tariff as an OUTUS plan (``outus/plan``), or None when there is none."""
    tar = store.tariff(tariff_id)
    if not tar:
        return None
    util = store.utility(tar["utility_id"]) if tar.get("utility_id") else None
    meter = store.meter(tar["meter_id"]) if tar.get("meter_id") else None
    plan = profile_v1.from_tariff_profile(
        tariff_io.from_local(util, tar, (meter or {}).get("timezone") or ""))
    plan["id"] = tar["id"]
    # The bridge keeps the billing day on the tariff, not in the profile's pricing.
    plan["billing"]["cycle_day"] = max(1, min(28, int(tar.get("billing_cycle_day") or 1)))
    if (util or {}).get("name"):
        plan["retailer"]["name"] = util["name"]
    return plan


def _plans(store, meter_id: str) -> list[dict[str, Any]]:
    return [p for t in store.tariffs() if t.get("meter_id") == meter_id
            for p in [outus_plan(store, t["id"])] if p]


def page(store, meter_id: str | None, today: dt.date) -> dict[str, Any]:
    """The meters to choose from, the chosen one (``meter_id``, else the default) and its
    setup steps."""
    meters = _meters(store)
    meter = next((m for m in meters if m["id"] == meter_id), None) or (meters[0] if meters else None)
    steps = setup.steps(store.sites(), meters, _plans(store, meter["id"]) if meter else [],
                        meter["id"] if meter else None, today)
    return {"meters": meters, "meter": meter, "steps": steps, "complete": setup.complete(steps)}


def _zone(store, plan: dict, meter: dict) -> ZoneInfo | None:
    """The plan's zone, else the meter's, its site's, or the site timezone from setup; None
    when none is set (the bill then uses UTC and says so)."""
    site = store.site(meter.get("site_id")) if meter.get("site_id") else None
    for name in (plan.get("timezone"), meter.get("timezone"), (site or {}).get("timezone"),
                 setup_wizard.site_timezone(store)):
        if name:
            try:
                return ZoneInfo(name)
            except (ZoneInfoNotFoundError, ValueError):
                continue
    return None


#: Each meter's ledger for its open period, kept between requests and fed only the
#: readings since the last one: a month of 30-second polls is ~90,000 rows a gateway.
_LEDGERS: dict[str, dict[str, Any]] = {}
SETTLE_S = 120
_LOCK = threading.Lock()


def _ledger(store, meter_id: str, gateway_ids: list[str], start: dt.datetime,
            now: dt.datetime) -> list[dict]:
    """The meter's 5-minute intervals from its gateways' grid readings, built by hems,
    including the current interval so far."""
    key = (int(start.timestamp()), tuple(gateway_ids))
    with _LOCK:
        led = _LEDGERS.get(meter_id)
        if led is None or led["key"] != key:
            led = _LEDGERS[meter_id] = {"key": key, "state": ledger.new_state(meter_id),
                                        "closed": [], "last": int(start.timestamp()) - 1}
        upto = int(now.timestamp())
        settled = upto - SETTLE_S
        if settled > led["last"]:
            for ts, gw, w in store.grid_readings(led["last"] + 1, settled, gateway_ids):
                led["closed"] += ledger.add_reading(led["state"], gw, ts, w)
            led["last"] = settled
        # The last SETTLE_S on a copy: a poll may still be writing a reading stamped earlier.
        state, tail = copy.deepcopy(led["state"]), []
        for ts, gw, w in store.grid_readings(led["last"] + 1, upto, gateway_ids):
            tail += ledger.add_reading(state, gw, ts, w)
        cur = ledger.open_interval(state)                 # the current five minutes, so far
        return led["closed"] + tail + ([cur] if cur else [])


def bill(store, meter_id: str | None, now: dt.datetime) -> dict[str, Any] | None:
    """The open period's bill for the meter (an OUTUS bill, provisional), worked out by hems
    from the plan in force and the ledger; None with no plan in force. ``now`` is aware."""
    meters = _meters(store)
    meter = next((m for m in meters if m["id"] == meter_id), None) or (meters[0] if meters else None)
    if meter is None:
        return None
    row = store.meter(meter["id"]) or {}
    plans = _plans(store, meter["id"])
    probe = hbilling.plan_in_force(plans, now.date())
    if probe is None:
        return None
    tz = _zone(store, probe, row)
    no_zone = tz is None
    tz = tz or ZoneInfo("UTC")
    local = now.astimezone(tz)
    plan = hbilling.plan_in_force(plans, local.date())
    if plan is None:
        return None
    plan = {**plan, "timezone": str(tz)}
    cyc = plan.get("billing") or {}
    start, end = periods.bounds(local, cyc.get("cycle", "monthly"), cyc.get("cycle_day", 1))
    ivs = _ledger(store, meter["id"], meter["gateway_ids"], start, local)
    out = hbilling.bill(plan, {"general": ivs}, start, end, now=local)
    out["meter"] = {"ref": meter["id"], "commodity": "electricity", "unit": "kWh"}
    out["x-now-rates"] = hbilling.now_rates(plan, local)     # band and rate now (Bill detail)
    out["x-tariffs"] = {t["id"]: t.get("name") or t["id"] for t in plan.get("tariffs") or []}
    out["x-timezone"] = str(tz)
    if no_zone:                       # TOU windows and the period's days are then in UTC
        out["x-timezone-missing"] = True
    return out
