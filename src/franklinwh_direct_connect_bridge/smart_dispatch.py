"""Smart Dispatch, plan only (#612 §7 phase 1, on ``hems.dispatch``).

The user's target and the utility's limits are asked once a plan is entered (hems's
questions, pre-filled answers "please confirm"). The 24-hour plan is worked out from:

- prices: the meter's OUTUS plan in force (``billing_page``), per 30 minutes;
- solar: the site's solar forecast (``solar_forecast``), when the location and size are set;
- home load: the load forecast (``load_forecast.predict``); an hour it has no history for
  is the hour-of-day average, else the always-on load from HEMS setup (owner 2026-11-25);
- the battery: SoC and off grid from the last poll, capacity and power from System setup or
  the user's constants, wear per kWh and round trip from Battery warranty & wear.

Phase 2 (#612): the plan as draft schedules (``drafts``); ``create``, which adds them to the
Scheduler as one-off tasks tagged ``ORIGIN``; and Auto (``auto_tick``, hourly from the
scheduler worker), Shadow (log only) or On. Nothing here writes to the gateway: the Scheduler
runs the tasks.
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

#: Below this (kW) a step's battery is idle: a Hold is a force standby.
IDLE_KW = 0.2
#: The tag on the Scheduler tasks Smart Dispatch creates (an edit in the Scheduler drops it:
#: the task is then the user's).
ORIGIN = "smart_dispatch"
#: Each action's name in the tab.
LABELS = {"charge": "Charge from grid", "discharge": "Export from battery", "hold": "Hold"}

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


#: How each load-forecast method reads in the plan's assumptions.
LOAD_METHODS = {"model": "the load model", "cold_start": "the weekday-hour average",
                "hour_of_day": "the hour-of-day average",
                "baseline": "your always-on load (HEMS setup)"}


def _always_on(store, gateway_id: str) -> float | None:
    """The always-on load (kW) the user gave in HEMS setup; None when not given."""
    from . import hems_setup
    v = hems_setup._answers(store, gateway_id).get("always_on_kw")
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _load(store, settings, gateway_id: str, fc: dict | None, now: float
          ) -> dict[int, tuple[float, str]]:
    """{hour start: (kW, method)} from the load forecast; empty when it can't predict. An
    hour with no history is the always-on load from HEMS setup, when given."""
    from . import load_forecast, site_location
    try:
        loc = site_location.for_gateway(settings, store, gateway_id)
        pts = load_forecast.predict(store, gateway_id, loc, fc, now,
                                    baseline_kwh=_always_on(store, gateway_id))
    except Exception as e:                                       # noqa: BLE001
        log.debug("Smart Dispatch: no load forecast: %s", e)
        return {}
    return {p["start"]: (float(p["kwh"]), p["method"]) for p in pts if p.get("kwh") is not None}


def _inputs(store, settings, gateway_id: str, now: float, plan: dict | None,
            kwp: float | None, battery: dict) -> list[dict]:
    """What the plan is using, each ``{key, label, value, status (ok, partial, missing),
    action}``: home load, solar, battery and tariff (owner 2026-11-25)."""
    from . import load_forecast
    from hems import forecast as hforecast
    try:
        days = load_forecast.history_days(store, gateway_id, now)
    except Exception:                                            # noqa: BLE001
        days = 0
    always = _always_on(store, gateway_id)
    full = hforecast.MIN_HISTORY_DAYS
    if days:
        value = f"{days} day{'s' if days != 1 else ''} of local history"
        value += "" if days >= full else f" (the full load model needs {full})"
    else:
        value = "No local history yet"
    value += (f"; always-on load {always:g} kW from HEMS setup for hours with no history"
              if always is not None else "; no always-on load in HEMS setup")
    value += "; FranklinWH cloud history isn't used yet"
    home = {"key": "home_load", "label": "Home load", "value": value,
            "status": "ok" if days >= full else "partial" if days or always is not None
            else "missing",
            "action": {"label": "Re-run HEMS setup", "wizard": "hems", "step": "usage"}}
    solar = {"key": "solar", "label": "Solar", "value": f"{kwp:g} kWp, forecast for your location"
             if kwp else "No solar size or location: planned without solar",
             "status": "ok" if kwp else "missing",
             "action": {"label": "Open Location & Solar", "tab": "settings"}}
    cap = battery.get("capacity_kwh")
    bat = {"key": "battery", "label": "Battery",
           "value": f"{cap:g} kWh, SoC {battery['soc_pct']:g}%" if cap and battery.get(
               "soc_pct") is not None else f"{cap:g} kWh" if cap else "Capacity not known",
           "status": "ok" if cap and battery.get("soc_pct") is not None else "partial" if cap
           else "missing", "action": {"label": "Open System setup", "tab": "settings"}}
    tariff = {"key": "tariff", "label": "Tariff",
              "value": (plan.get("name") or "Utility plan") if plan else "No utility plan",
              "status": "ok" if plan else "missing",
              "action": {"label": "Open Billing & Utilities", "tab": "energy_costs"}}
    return [home, solar, bat, tariff]


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


def _direction(step: dict) -> str | None:
    """The force a step needs: charge, discharge, standby, or None (self-consumption, or a
    Hold that still charges from solar: forcing that charge could take it from the grid)."""
    a, kw = step["action"], float(step["battery_kw"])
    if a == "charge":
        return "charge"
    if a == "discharge":
        return "discharge"
    if a == "hold":
        if abs(kw) <= IDLE_KW:
            return "standby"
        return "discharge" if kw < 0 else None
    return None


def drafts(result: dict, gateway_id: str, tz, *, existing: list | None = None,
           mode: str | None = None, force: tuple[bool, str] = (True, "")) -> dict:
    """The plan as one-off scheduler tasks: each run of the same action and force is one
    task, split at midnight (site time ``tz``), at the run's highest kW and aiming for the
    plan's SoC at its end. ``clashes`` names the enabled schedules on this gateway that drive
    the battery in the same window. Nothing is created."""
    runs: list[list[dict]] = []
    for s in result.get("steps") or []:
        d = _direction(s)
        if d is None:
            continue
        day = dt.datetime.fromtimestamp(s["start"], tz).date()
        last = runs[-1][-1] if runs else None
        if (last is not None and last["action"] == s["action"] and _direction(last) == d
                and last["start"] + last["duration_s"] == s["start"]
                and dt.datetime.fromtimestamp(last["start"], tz).date() == day):
            runs[-1].append(s)
        else:
            runs.append([s])
    tasks = []
    for run in runs:
        d = _direction(run[0])
        start = dt.datetime.fromtimestamp(run[0]["start"], tz)
        end = dt.datetime.fromtimestamp(run[-1]["start"] + run[-1]["duration_s"], tz)
        action: dict = {"kind": "force", "direction": d, "unit": "kw"}
        if d != "standby":
            action["power"] = round(max(abs(float(s["battery_kw"])) for s in run), 1)
            action["target_soc"] = int(round(run[-1]["soc_pct"]))
        label = LABELS[run[0]["action"]]
        spec = {"trigger_type": "once", "start_date": start.date().isoformat(),
                "end_date": start.date().isoformat(), "fire_at": start.strftime("%H:%M"),
                "duration_min": int((end - start).total_seconds() // 60),
                "gateway_id": gateway_id, "action": action}
        tasks.append({"name": f"Smart Dispatch: {label} {start:%H:%M}–{end:%H:%M}",
                      "action": run[0]["action"], "label": label, "start": run[0]["start"],
                      "end": run[-1]["start"] + run[-1]["duration_s"],
                      "reason": run[0]["reason"], "spec": spec,
                      "clashes": _clashes(spec, existing or [], start, tz)})
    notes = []
    if tasks and mode == "Time-of-Use":
        notes.append("The gateway is in Time-of-Use: outside these windows its schedule in "
                     "the FranklinWH app still charges and discharges")
    if tasks and not force[0]:
        notes.append(f"Force charge and discharge need the Modbus client: {force[1]}")
    return {"tasks": tasks, "notes": notes}


def _clashes(spec: dict, existing: list, start: dt.datetime, tz) -> list[str]:
    """Names of the enabled schedules on the gateway that drive the battery while ``spec``
    runs, from the scheduler's own day timeline."""
    from . import scheduler
    gw = spec["gateway_id"]
    mine = scheduler.resource_for(spec["action"], gw)
    others = [e for e in existing
              if scheduler.resources_contend(mine, scheduler.resource_for(e.get("action"), gw))]
    midnight = start.replace(hour=0, minute=0, second=0, microsecond=0)
    tl = scheduler.timeline_segments(others, midnight, gw)
    lo = start.hour * 60 + start.minute
    hi = lo + spec["duration_min"]
    names = []
    for seg in tl["segments"] + tl.get("site", []):
        if any(b0 < hi and lo < b1 for b0, b1 in seg["blocks"]) and seg["name"] not in names:
            names.append(seg["name"])
    return names


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
           "controls": False, "result": None, "decision": None, "drafts": None,
           "auto": _auto_view(store, gateway_id),
           "inputs": _inputs(store, settings, gateway_id, now, plan, kwp, battery)}
    if missing or issues:
        return out

    start = int(now) // STEP_S * STEP_S
    key = json.dumps([start, values, plan.get("id"), battery], sort_keys=True, default=str)
    hit = _cache.get(gateway_id)
    if hit and not force and answers is None and hit[1] == key and time.monotonic() - hit[0] < CACHE_S:
        return {**out, **hit[2], "decision": hdispatch.decide(hit[2]["result"], now),
                "drafts": _drafts(store, gateway_id, hit[2]["result"], power)}

    load = _load(store, settings, gateway_id, fc, now)
    steps = hdispatch.step_prices(plan, start, STEPS, STEP_S)
    no_load, methods = 0, {}
    for s in steps:
        hour = s["start"] // 3600 * 3600
        s["solar_kw"] = solar.get(hour, 0.0)
        if hour in load:
            s["load_kw"], m = load[hour]
            methods[m] = methods.get(m, 0) + 1
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
    if methods:
        notes.append("Home load: " + ", ".join(
            f"{n} of {STEPS} steps from {LOAD_METHODS.get(m, m)}" for m, n in methods.items()))
    if power.get("mode") == "Emergency Backup" and values.get("objective") != "backup":
        notes.append("The gateway is in Emergency Backup: on its own it keeps the battery "
                     "charged; the comparison is with Self-Consumption")
    result["assumptions"] = result["assumptions"] + notes
    # The tariff under each step, for the tab's shading and bands (owner 2026-11-25).
    for s, p in zip(result["steps"], steps):
        s["band"], s["demand_rate"] = p.get("band"), float(p.get("demand_rate") or 0.0)
        s["solar_kw"], s["load_kw"] = float(p.get("solar_kw") or 0.0), float(p.get("load_kw") or 0.0)
    result["energy"] = _energy(result["steps"])
    planned = {"result": result, "planned_at": int(now), "currency": plan.get("currency")}
    if answers is None:
        _cache[gateway_id] = (time.monotonic(), key, planned)
    return {**out, **planned, "decision": hdispatch.decide(result, now),
            "drafts": _drafts(store, gateway_id, result, power)}


def _site_zone(store):
    from . import load_forecast
    return load_forecast._zone(store)


def _drafts(store, gateway_id: str, result: dict, power: dict) -> dict:
    from . import battery_control
    rows = store.schedules()
    out = drafts(result, gateway_id, _site_zone(store),
                 existing=[e for e in rows if e.get("origin") != ORIGIN],
                 mode=power.get("mode"), force=battery_control.available())
    out["in_scheduler"] = len(_ours(rows, gateway_id))
    return out


def _ours(rows: list, gateway_id: str) -> list[dict]:
    return [e for e in rows if e.get("origin") == ORIGIN and e.get("gateway_id") == gateway_id]


def _window(entry: dict, tz) -> tuple[float, float]:
    """A one-off task's (start, end) timestamps in site time ``tz``."""
    h, m = map(int, str(entry.get("fire_at") or "00:00").split(":"))
    start = dt.datetime.combine(dt.date.fromisoformat(entry["start_date"]), dt.time(h, m),
                                tzinfo=tz).timestamp()
    return start, start + int(entry.get("duration_min") or 0) * 60


def _same(spec: dict) -> str:
    """What makes two one-off tasks the same task."""
    return json.dumps([spec.get(k) for k in ("start_date", "fire_at", "duration_min", "action")],
                      sort_keys=True)


def create(store, settings, gateway_id: str, now: float | None = None, *,
           dry_run: bool = False) -> dict:
    """Add the drafts to the Scheduler as one-off tasks tagged ``ORIGIN``. Its own tasks that
    haven't started are kept when the plan still has them and replaced when it doesn't; one
    running is left be (a draft over it is skipped), and so is every schedule of the user's (a
    draft that clashes with one is skipped). ``dry_run``: what it would do, nothing changed
    (Auto's Shadow). ValueError when there is no plan or force can't run."""
    import uuid

    from . import battery_control, scheduler
    now = time.time() if now is None else now
    v = view(store, settings, gateway_id, now)
    if v["drafts"] is None:
        raise ValueError("No plan yet: " + "; ".join(
            [m["todo"] for m in v["missing"]] + v["issues"]))
    ok, why = battery_control.available()
    if not ok:
        raise ValueError(f"Force charge and discharge need the Modbus client: {why}")
    tz = _site_zone(store)
    wanted = {_same(t["spec"]) for t in v["drafts"]["tasks"] if t["end"] > now}
    replaced, running, kept = [], [], set()
    for e in _ours(store.schedules(), gateway_id):
        try:
            w = _window(e, tz)
        except (KeyError, ValueError):
            continue
        if w[0] > now:
            if _same(e) in wanted and _same(e) not in kept:
                kept.add(_same(e))
                continue
            replaced.append(e["name"])
            if not dry_run:
                store.delete_schedule(e["id"])
                _log(store, e["id"], e["name"], "deleted", "replaced by Smart Dispatch",
                     gateway_id)
        elif now < w[1]:
            running.append(w)
    created, skipped = [], []
    for t in v["drafts"]["tasks"]:
        if t["end"] <= now or _same(t["spec"]) in kept:
            continue
        if t["clashes"]:
            skipped.append({"name": t["name"], "why": "clashes with " + ", ".join(t["clashes"])})
            continue
        if any(t["start"] < r1 and r0 < t["end"] for r0, r1 in running):
            skipped.append({"name": t["name"],
                            "why": "a Smart Dispatch task is already running then"})
            continue
        # Shaped as the Scheduler saves one (its card and form read these lists).
        spec = scheduler.normalize_spec({"conditions": [], "exit_conditions": [],
                                         **t["spec"], "origin": ORIGIN})
        errors = scheduler.validate_spec(spec)
        if errors:
            skipped.append({"name": t["name"], "why": "; ".join(errors)})
            continue
        if not dry_run:
            sid = uuid.uuid4().hex[:12]
            store.create_schedule(sid=sid, name=t["name"], spec=spec, enabled=True)
            _log(store, sid, t["name"], "created", "created by Smart Dispatch", gateway_id)
        created.append(t["name"])
    if not dry_run:
        _cache.pop(gateway_id, None)
    return {"created": created, "replaced": replaced, "kept": len(kept), "skipped": skipped}


# ── Auto (#612 phase 2, step 3) ──────────────────────────────────────────────────────────
#: app_config: Auto's mode and when Shadow started, per gateway.
AUTO_KEY = "smart_dispatch_auto:{gw}"
#: app_config: Auto's runs, newest first.
AUTO_LOG_KEY = "smart_dispatch_auto_log:{gw}"
AUTO_MODES = ("off", "shadow", "on")
#: How often Auto works the plan out again (s), and Shadow's run before On is allowed.
AUTO_S, SHADOW_S = 3600, 7 * 86400
#: Runs kept in the log: a week and a day of hourly runs.
AUTO_LOG_KEEP = 8 * 24

_last_auto: dict[str, float] = {}   # gateway -> when Auto last ran (this process)


def _json(store, key: str, default):
    try:
        v = store.get_config(key)
        return json.loads(v) if v else default
    except Exception:                                            # noqa: BLE001
        return default


def auto(store, gateway_id: str) -> dict:
    """Auto's mode, when Shadow started, when On is allowed, and its log (newest first)."""
    a = _json(store, AUTO_KEY.format(gw=gateway_id), {})
    since = a.get("shadow_since")
    return {"mode": a.get("mode") or "off", "shadow_since": since,
            "on_allowed_at": since + SHADOW_S if since is not None else None,
            "log": _json(store, AUTO_LOG_KEY.format(gw=gateway_id), [])}


def _auto_view(store, gateway_id: str) -> dict:
    a = auto(store, gateway_id)
    return {**a, "log": a["log"][:24]}


def set_auto(store, gateway_id: str, mode: str, now: float | None = None) -> dict:
    """Set Auto's mode. On only after a week of Shadow (kept when Auto is turned off).
    ValueError otherwise."""
    now = time.time() if now is None else now
    if mode not in AUTO_MODES:
        raise ValueError(f"Auto is one of {', '.join(AUTO_MODES)}, not '{mode}'")
    a = _json(store, AUTO_KEY.format(gw=gateway_id), {})
    since = a.get("shadow_since")
    if mode == "shadow" and since is None:
        since = now
    if mode == "on":
        if since is None:
            raise ValueError("Run Auto in Shadow for 7 days before turning it On")
        left = since + SHADOW_S - now
        if left > 0:
            raise ValueError(f"Auto can be On after 7 days of Shadow: "
                             f"{left / 86400:.1f} day(s) left")
    store.set_config(AUTO_KEY.format(gw=gateway_id),
                     json.dumps({"mode": mode, "shadow_since": since}))
    _last_auto.pop(gateway_id, None)                 # the next tick runs it
    return auto(store, gateway_id)


def auto_tick(store, settings, gateway_id: str, now: float | None = None) -> dict | None:
    """About hourly, Auto's run: Shadow logs what Create schedules would do, On does it.
    Returns the log entry, or None when it didn't run (Off, or not an hour yet)."""
    now = time.time() if now is None else now
    mode = auto(store, gateway_id)["mode"]
    if mode == "off":
        return None
    last = _last_auto.get(gateway_id)
    if last is not None and now - last < AUTO_S:
        return None
    _last_auto[gateway_id] = now
    entry: dict = {"ts": now, "mode": mode}
    try:
        out = create(store, settings, gateway_id, now, dry_run=mode == "shadow")
        entry.update(create=out["created"], replace=out["replaced"], kept=out["kept"],
                     skipped=out["skipped"])
    except ValueError as e:
        entry["error"] = str(e)
    except Exception as e:                                       # noqa: BLE001
        log.warning("Smart Dispatch Auto [%s] failed: %s", gateway_id, e)
        entry["error"] = f"{type(e).__name__}: {e}"
    key = AUTO_LOG_KEY.format(gw=gateway_id)
    store.set_config(key, json.dumps([entry, *_json(store, key, [])][:AUTO_LOG_KEEP]))
    return entry


def _log(store, sid: str, name: str, status: str, result: str, gateway_id: str) -> None:
    try:
        store.log_schedule_event(sid, name, status, result, gateway_id=gateway_id)
    except Exception:                                            # noqa: BLE001
        pass


def _energy(steps: list[dict]) -> dict:
    """The plan's 24 hours in kWh (owner 2026-11-25): sources (solar, grid import, battery
    discharge), loads (home, battery charge) and exports (to the grid, from the battery,
    and solar curtailed)."""
    def total(f):
        return round(sum(f(s) * (s.get("duration_s") or STEP_S) / 3600.0 for s in steps), 2)
    return {"solar_kwh": total(lambda s: s.get("solar_kw") or 0.0),
            "import_kwh": round(sum(s.get("grid_import_kwh") or 0.0 for s in steps), 2),
            "battery_discharge_kwh": total(lambda s: max(-(s.get("battery_kw") or 0.0), 0.0)),
            "load_kwh": total(lambda s: s.get("load_kw") or 0.0),
            "battery_charge_kwh": total(lambda s: max(s.get("battery_kw") or 0.0, 0.0)),
            "export_kwh": round(sum(s.get("grid_export_kwh") or 0.0 for s in steps), 2),
            "battery_export_kwh": total(lambda s: s.get("battery_export_kw") or 0.0),
            "curtailed_kwh": round(sum(s.get("curtailed_kwh") or 0.0 for s in steps), 2)}


def actuals(store, gateway_id: str, now: float | None = None) -> dict:
    """What the battery and the grid did each half hour from the site's midnight to now, for
    the tab's Actuals (owner 2026-11-25). ``battery_kw`` uses the plan's sign (+ charging);
    import and export are from the half hour's mean grid power."""
    from . import load_forecast
    now = time.time() if now is None else now
    tz = load_forecast._zone(store)
    local = dt.datetime.fromtimestamp(now, tz)
    start = int(local.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
    rows = store.query(start, int(now), STEP_S, gateway=gateway_id) if store is not None else []

    def kw(w, sign=1.0):
        return None if w is None else round(sign * w / 1000.0, 2)
    out = []
    for r in rows:
        g = r.get("grid_w")
        out.append({"start": r["ts"], "battery_kw": kw(r.get("battery_w"), -1.0),
                    "soc_pct": r.get("soc"),
                    "import_kw": None if g is None else kw(max(g, 0.0)),
                    "export_kw": None if g is None else kw(max(-g, 0.0)),
                    "solar_kw": kw(r.get("solar_w")), "load_kw": kw(r.get("load_w"))})
    return {"start": start, "end": int(now), "timezone": str(tz), "steps": out}
