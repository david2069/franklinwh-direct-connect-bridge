"""Smart Dispatch, plan only (#612 §7 phase 1, on ``hems.dispatch``).

The user's target and the utility's limits are asked once a plan is entered (hems's
questions, pre-filled answers "please confirm"). The 24-hour plan is worked out from:

- prices: the meter's OUTUS plan in force (``billing_page``), per 30 minutes;
- solar: the site's solar forecast (``solar_forecast``), when the location and size are set;
- home load: the load forecast (``load_forecast.predict``);
- the battery: SoC and off grid from the last poll, capacity and power from System setup or
  the user's constants, wear per kWh and round trip from Battery warranty & wear.

Nothing here controls anything: no device write, no schedule. Auto comes in a later phase.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import time

from hems import dispatch as hdispatch
from hems import wear as hwear

log = logging.getLogger(__name__)

#: app_config: the answers, per gateway.
KEY = "smart_dispatch:{gw}"
#: The answers PUT accepts (the solar size lives in Settings → Location & Solar).
FIELDS = ("objective", "min_soc_pct", "max_soc_pct", "grid_charge", "grid_charge_kw",
          "export", "export_kw", "battery_export", "demand_aware")
#: Steps of the plan, and their length (s).
STEPS, STEP_S = 48, 1800
#: A plan is reused for this long (s) unless asked again (Re-evaluate).
CACHE_S = 900
#: Round trip used until hems has measured one.
ROUND_TRIP = 0.9

_cache: dict[str, tuple[float, str, dict]] = {}   # gateway -> (monotonic, inputs key, view)


def _answers(store, gateway_id: str) -> dict:
    try:
        v = store.get_config(KEY.format(gw=gateway_id)) if store is not None else None
        return json.loads(v) if v else {}
    except Exception:                                            # noqa: BLE001
        return {}


def save(store, gateway_id: str, body: dict) -> dict:
    """Set answers (null clears one back to its pre-fill). Unknown keys: ValueError."""
    bad = [k for k in body if k not in FIELDS]
    if bad:
        raise ValueError(f"unknown Smart Dispatch field(s): {', '.join(bad)}")
    cur = _answers(store, gateway_id)
    for k, v in body.items():
        if v is None:
            cur.pop(k, None)
        else:
            cur[k] = v
    store.set_config(KEY.format(gw=gateway_id), json.dumps(cur))
    _cache.pop(gateway_id, None)
    return cur


def _plan(store, gateway_id: str, today: dt.date) -> dict | None:
    """The meter's OUTUS plan in force today, with its zone set (as the bill does)."""
    from hems import billing as hbilling

    from . import billing_page, scheduler
    meter = scheduler._meter_for_gateway(store, gateway_id)
    if not meter:
        return None
    plan = hbilling.plan_in_force(billing_page._plans(store, meter["id"]), today)
    if plan is None:
        return None
    tz = billing_page._zone(store, plan, store.meter(meter["id"]) or meter)
    return {**plan, "timezone": str(tz) if tz else "UTC"}


def _solar(store, settings, gateway_id: str) -> tuple[dict | None, dict[int, float], float | None]:
    """(forecast, {hour start: kW}, kWp); empty without a location and solar size."""
    from . import site_location, solar_forecast
    loc = site_location.for_gateway(settings, store, gateway_id)
    if not (site_location.configured(loc) and loc.get("kwp")):
        return None, {}, None
    fc = solar_forecast.forecast(loc["latitude"], loc["longitude"], kwp=loc["kwp"],
                                 tilt=loc["pv_tilt"], azimuth=loc["pv_azimuth"], store=store)
    off = dt.timezone(dt.timedelta(seconds=int((fc or {}).get("utc_offset_seconds") or 0)))
    out = {}
    for h in (fc or {}).get("hourly") or []:
        try:
            t = dt.datetime.fromisoformat(h["time"]).replace(tzinfo=off)
        except (KeyError, TypeError, ValueError):
            continue
        if h.get("kw") is not None:
            out[int(t.timestamp())] = float(h["kw"])
    return fc, out, float(loc["kwp"])


def _load(store, settings, gateway_id: str, fc: dict | None, now: float
          ) -> tuple[dict[int, float], str | None]:
    """({hour start: kW}, method) from the load forecast; empty when it can't predict."""
    from . import load_forecast, site_location
    try:
        loc = site_location.for_gateway(settings, store, gateway_id)
        pts = load_forecast.predict(store, gateway_id, loc, fc, now)
    except Exception as e:                                       # noqa: BLE001
        log.debug("Smart Dispatch: no load forecast: %s", e)
        return {}, None
    return ({p["start"]: float(p["kwh"]) for p in pts if p.get("kwh") is not None},
            (pts[0].get("method") if pts else None))


def _battery(store, gateway_id: str, now: float) -> tuple[dict, list[str]]:
    """The battery for the planner and where each value came from."""
    from . import constants, state, system_setup, wear
    gw = state.get_gateway(gateway_id)
    power = ((gw.last_summary or {}).get("power") or {}) if gw is not None else {}
    consts = constants.values(store)
    cap = system_setup.cached_capacity_kwh(store, gateway_id, getattr(gw, "host", None))
    cap_src = "System setup (aPower count × model)"
    if not cap:
        cap, cap_src = float(consts.get("battery_capacity_kwh") or 0.0), "your constants"
    kw = float(consts.get("battery_max_power_kw") or 5.0)
    rt, rt_src = ROUND_TRIP, f"{ROUND_TRIP:.0%} until measured"
    try:
        med = wear.efficiency(store, gateway_id, now).get("median")
        if med:
            rt, rt_src = float(med), "measured (Battery warranty & wear)"
    except Exception:                                            # noqa: BLE001
        pass
    per_kwh = 0.0
    try:
        c = hwear.cost_per_kwh(wear.fields(store, gateway_id))
        per_kwh = float((c or {}).get("per_kwh") or 0.0)
    except Exception:                                            # noqa: BLE001
        pass
    b = {"capacity_kwh": cap, "soc_pct": power.get("soc"), "max_charge_kw": kw,
         "max_discharge_kw": kw, "round_trip": rt, "wear_per_kwh": per_kwh}
    sources = [f"Capacity {cap:g} kWh from {cap_src}" if cap else "Capacity not known",
               f"Power {kw:g} kW from your constants", f"Round trip {rt:.0%}, {rt_src}",
               f"Wear {per_kwh:.3f} per kWh" if per_kwh else "Wear not set (no cost per kWh)"]
    return b, sources


def _demand_peak(store, gateway_id: str) -> float:
    from . import billing
    try:
        return float(billing.billing_read(store, gateway_id).get("demand.peak_kw") or 0.0)
    except Exception:                                            # noqa: BLE001
        return 0.0


def view(store, settings, gateway_id: str, now: float | None = None, *,
         answers: dict | None = None, force: bool = False) -> dict:
    """The tab: the questions (with the user's answers or pre-fills), what is missing, and,
    once everything is there, the 24-hour plan and the action now. With ``answers`` those
    (not yet saved) are shown and planned instead of the stored ones."""
    from . import load_forecast, state
    now = time.time() if now is None else now
    if settings is None:
        from .config import get_settings
        settings = get_settings()
    stored = _answers(store, gateway_id)
    a = stored if answers is None else answers
    tz = load_forecast._zone(store)
    today = dt.datetime.fromtimestamp(now, tz).date()
    plan = _plan(store, gateway_id, today)
    fc, solar, kwp = _solar(store, settings, gateway_id)
    qs = hdispatch.questions(plan, solar_kwp=kwp, values=a)
    for q in qs:
        if q["key"] == "solar_kwp":
            q.update(readonly=True, where="Settings → Location & Prices → Location & Solar")
    values = {q["key"]: q.get("value") for q in qs if q["kind"] != "info"}
    issues = hdispatch.check(values)
    battery, sources = _battery(store, gateway_id, now)
    gw = state.get_gateway(gateway_id)
    power = ((gw.last_summary or {}).get("power") or {}) if gw is not None else {}

    missing = []
    if plan is None:
        missing.append({"key": "plan", "todo": "Add your utility plan in Billing & Utilities",
                        "tab": "energy_costs"})
    if not battery["capacity_kwh"]:
        missing.append({"key": "capacity", "todo": "Set your aPower model in System setup",
                        "tab": "settings"})
    if battery["soc_pct"] is None:
        missing.append({"key": "soc", "todo": "Waiting for the gateway's first reading",
                        "tab": None})
    out = {"saved": bool(stored), "questions": qs, "issues": issues, "missing": missing,
           "facts": hdispatch.plan_facts(plan), "plan_name": (plan or {}).get("name"),
           "timezone": (plan or {}).get("timezone") or str(tz), "sources": sources,
           "mode": power.get("mode"), "off_grid": bool(power.get("off_grid")),
           "controls": False, "result": None, "decision": None}
    if missing or issues:
        return out

    start = int(now) // STEP_S * STEP_S
    key = json.dumps([start, values, plan.get("id"), battery], sort_keys=True, default=str)
    hit = _cache.get(gateway_id)
    if hit and not force and answers is None and hit[1] == key and time.monotonic() - hit[0] < CACHE_S:
        return {**out, **hit[2], "decision": hdispatch.decide(hit[2]["result"], now)}

    load, method = _load(store, settings, gateway_id, fc, now)
    steps = hdispatch.step_prices(plan, start, STEPS, STEP_S)
    no_load = 0
    for s in steps:
        hour = s["start"] // 3600 * 3600
        s["solar_kw"] = solar.get(hour, 0.0)
        if hour in load:
            s["load_kw"] = load[hour]
        else:
            s["load_kw"], no_load = 0.0, no_load + 1
    result = hdispatch.plan_24h(steps, battery, values, state={
        "off_grid": bool(power.get("off_grid")),
        "demand_peak_kw": _demand_peak(store, gateway_id)})
    notes = []
    if not solar:
        notes.append("No solar forecast: set your location and solar size in Settings")
    if no_load:
        notes.append(f"No load forecast for {no_load} of {STEPS} steps: planned with 0 kW")
    if method:
        notes.append(f"Home load from the load forecast ({method})")
    if power.get("mode") == "Emergency Backup" and values.get("objective") != "backup":
        notes.append("The gateway is in Emergency Backup: on its own it keeps the battery "
                     "charged; the comparison is with Self-Consumption")
    result["assumptions"] = result["assumptions"] + notes
    planned = {"result": result, "planned_at": int(now), "currency": plan.get("currency")}
    if answers is None:
        _cache[gateway_id] = (time.monotonic(), key, planned)
    return {**out, **planned, "decision": hdispatch.decide(result, now)}
