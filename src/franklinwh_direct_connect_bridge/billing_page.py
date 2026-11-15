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


def _readings_ledger(store, meter_id: str, gateway_ids: list[str], start: dt.datetime,
                     end: dt.datetime) -> list[dict]:
    """5-minute intervals for [start, end) from the readings, not kept (a closed period)."""
    state = ledger.new_state(meter_id)
    out: list[dict] = []
    for ts, gw, w in store.grid_readings(int(start.timestamp()), int(end.timestamp()) - 1, gateway_ids):
        out += ledger.add_reading(state, gw, ts, w)
    cur = ledger.open_interval(state)
    return out + ([cur] if cur else [])


def _final_bill(store, meter: dict, plan: dict, tz: ZoneInfo, start: dt.datetime,
                end: dt.datetime, n: int = 1) -> dict:
    ivs = _readings_ledger(store, meter["id"], meter["gateway_ids"], start, end)
    out = hbilling.bill({**plan, "timezone": str(tz)}, {"general": ivs}, start, end)
    out["id"] = f"{meter['id']}:{start.date().isoformat()}" + (f":{n}" if n > 1 else "")
    out["meter"] = {"ref": meter["id"], "commodity": "electricity", "unit": "kWh"}
    out["x-tariffs"] = {t["id"]: t.get("name") or t["id"] for t in plan.get("tariffs") or []}
    out["x-timezone"] = str(tz)                       # the period's dates are in this zone
    return out


def _context(store, meter_id: str | None):
    meters = _meters(store)
    meter = next((m for m in meters if m["id"] == meter_id), None) or (meters[0] if meters else None)
    if meter is None:
        return None, [], None
    return meter, _plans(store, meter["id"]), store.meter(meter["id"]) or {}


def closed_bills(store, meter_id: str | None, now: dt.datetime, limit: int = 12,
                 include_superseded: bool = False) -> list[dict]:
    """The meter's closed periods' bills, newest first. A period not yet billed is worked out
    now by hems (final) and kept; a kept one is never recalculated here. Periods before the
    first reading, or with no plan in force, have no bill."""
    meter, plans, row = _context(store, meter_id)
    if meter is None or not plans:
        return []
    first = store.first_reading_ts(meter["gateway_ids"])
    if first is None:
        return []
    probe = plans[0]
    tz = _zone(store, probe, row) or ZoneInfo("UTC")
    local = now.astimezone(tz)
    cyc = (hbilling.plan_in_force(plans, local.date()) or probe).get("billing") or {}
    cur_start, _ = periods.bounds(local, cyc.get("cycle", "monthly"), cyc.get("cycle_day", 1))
    end, out = cur_start, []
    while len(out) < limit and end.timestamp() > first:
        p_local = end - dt.timedelta(seconds=1)
        plan = hbilling.plan_in_force(plans, p_local.date())
        c = (plan or {}).get("billing") or cyc
        start, _ = periods.bounds(p_local, c.get("cycle", "monthly"), c.get("cycle_day", 1))
        if plan is not None:
            kept = store.outus_bills(meter["id"], include_superseded=include_superseded,
                                     period_start=start.timestamp())
            if not kept:
                b = _final_bill(store, meter, plan, tz, start, end)
                store.save_outus_bill(b, meter["id"], start.timestamp(), end.timestamp())
                kept = [b]
            out += kept
        end = start
    return out


def recalculate(store, bill_id: str, now: dt.datetime) -> dict | None:
    """Work a kept bill out again with today's plan and readings: a new bill that supersedes
    it (OUTUS §6). The old one stays, marked superseded."""
    old = store.outus_bill(bill_id)
    if old is None or old.get("status") == "superseded":
        return None
    meter, plans, row = _context(store, old["x-meter-id"])
    if meter is None or not plans:
        return None
    tz = _zone(store, plans[0], row) or ZoneInfo("UTC")
    start = dt.datetime.fromtimestamp(old["x-start"], tz)
    end = dt.datetime.fromtimestamp(old["x-end"], tz)
    plan = hbilling.plan_in_force(plans, (end - dt.timedelta(seconds=1)).date())
    if plan is None:
        return None
    n = len(store.outus_bills(meter["id"], include_superseded=True, period_start=start.timestamp())) + 1
    new = _final_bill(store, meter, plan, tz, start, end, n)
    new["supersedes"] = bill_id
    store.supersede_outus_bill(bill_id)
    store.save_outus_bill(new, meter["id"], start.timestamp(), end.timestamp())
    return new


def usage(store, meter_id: str | None, start: dt.datetime, end: dt.datetime) -> dict | None:
    """The meter's 5-minute usage for [start, end) as an OUTUS usage document."""
    meter, _plans_, _row = _context(store, meter_id)
    if meter is None:
        return None
    ivs = _readings_ledger(store, meter["id"], meter["gateway_ids"], start, end)

    def iso(ts):
        return dt.datetime.fromtimestamp(ts, dt.timezone.utc).isoformat().replace("+00:00", "Z")
    return {"type": "outus/usage", "version": 1,
            "meter": {"ref": meter["id"], "commodity": "electricity", "unit": "kWh"},
            "channels": [{"channel": "general", "intervals": [
                {**{k: v for k, v in iv.items() if k != "start"}, "start": iso(iv["start"])}
                for iv in ivs]}]}
