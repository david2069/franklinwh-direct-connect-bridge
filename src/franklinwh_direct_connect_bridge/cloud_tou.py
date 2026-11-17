"""The FranklinWH TOU schedule, from the Cloud API (owner 2026-11-16).

The aGate runs the TOU schedule set in the FranklinWH app; the local API can't read it
(1408 returns no timers), so the bridge reads ``get_tou_dispatch_detail`` and keeps a
dated copy: at start-up (the first good cloud pass) and whenever TOU mode is set, and on
**Sync now**. A copy is stored only when the schedule changed; otherwise the latest copy's
``checked_ts`` moves on.

While TOU mode is on, the aGate follows those blocks, so a bridge Force (charge, discharge
or standby) that contradicts the block it runs in works against it: ``conflicts`` lists
those, one row per schedule and block.

The bridge recommends its own schedules over FranklinWH TOU. TOU's one advantage is that
it runs without the bridge, which is also its drawback: the bridge can't see, condition or
notify on it. ``import_plan`` turns the TOU blocks into bridge schedules, created disabled,
for Self-Consumption as the base mode. Nothing is ever written to the cloud or the aGate.

The copy keeps the buy and sell rates (``eletic*``) for each day type, so a band can cost
one thing on weekdays and another at weekends (#656; owner 2026-11-18: a band per day
type). The cloud gives no unit: it's taken as the local currency per kWh, please confirm.
The schedule is also re-read once a day (``daily``). ``ha_payload`` works out Home
Assistant's TOU Schedule, Dispatch Now/Next and Tariff Now/Next from the copy (#421).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import time
from typing import Any

from . import scheduler

#: dispatchId → what the FranklinWH app calls it (franklinwh_cloud DISPATCH_CODES).
DISPATCH = {1: "aPower to home", 2: "aPower on standby", 3: "aPower charges from solar",
            6: "Self-consumption", 7: "aPower to home/grid",
            8: "aPower charges from solar/grid"}
#: waveType → tariff period (franklinwh_cloud WAVE_TYPES).
WAVE = {0: "Off-peak", 1: "Mid-peak", 2: "On-peak", 4: "Super off-peak"}
#: waveType → the ``eletic*`` field suffix of its rate. Sharp has no known band; it is kept.
RATE_FIELD = {0: "Valley", 1: "Shoulder", 2: "Peak", 4: "SuperOffPeak"}
#: The cloud gives the rates without a unit (#656).
RATE_UNIT = "local currency per kWh (assumed; please confirm against the FranklinWH app)"
#: How often the schedule is read again without another reason (owner 2026-11-18).
DAILY_S = 86_400
#: dayType → weekdays (0 = Monday), as the library's ``_match_day_type``.
DAY_TYPE = {1: [0, 1, 2, 3, 4], 2: [5, 6], 3: [0, 1, 2, 3, 4, 5, 6]}

#: The bridge's base mode after an import is Self-Consumption: these need no schedule.
BASE = {1, 6}
#: TOU dispatches with a bridge action: Force charge, discharge, standby.
FORCE = {8: "charge", 7: "discharge", 2: "standby"}
#: What each TOU dispatch has the battery do, against a bridge Force direction (owner
#: 2026-11-16): a clash is a Force whose direction contradicts the block's. Mode, reserve,
#: off-grid and smart-circuit schedules never clash.
TOU_BATTERY = {8: "charge", 3: "charge", 7: "discharge", 1: "discharge", 6: "discharge",
               2: "standby"}


def _months(text: Any) -> list[int]:
    out = []
    for p in str(text or "").split(","):
        try:
            out.append(int(p))
        except ValueError:
            continue
    return out


def _rates(d: dict) -> dict[str, dict]:
    """A day type's buy and sell rate per band; a band with neither is left out (the
    cloud's ``null`` means not used, not free)."""
    out = {}
    for wave, field in [*RATE_FIELD.items(), (None, "Sharp")]:
        buy, sell = d.get(f"eleticRate{field}"), d.get(f"eleticSell{field}")
        if buy is not None or sell is not None:
            out[WAVE[wave] if wave is not None else "Sharp"] = {"buy": buy, "sell": sell}
    return out


def schedule(result: dict) -> dict[str, Any]:
    """``get_tou_dispatch_detail``'s ``result`` as seasons → day types → blocks."""
    tpl = result.get("template") or {}
    seasons = []
    for s in result.get("strategyList") or []:
        days = []
        for d in s.get("dayTypeVoList") or []:
            blocks = []
            for b in d.get("detailVoList") or []:
                did = b.get("dispatchId")
                blocks.append({"start": b.get("startHourTime") or "00:00",
                               "end": b.get("endHourTime") or "24:00", "dispatch_id": did,
                               "dispatch": DISPATCH.get(did, f"dispatch {did}"),
                               "wave": WAVE.get(b.get("waveType"), "")})
            days.append({"name": d.get("dayName") or "", "day_type": d.get("dayType"),
                         "weekdays": DAY_TYPE.get(d.get("dayType"), []), "blocks": blocks,
                         "rates": _rates(d), "grid_fee": d.get("eleticRateGridFee")})
        seasons.append({"name": s.get("seasonName") or "", "months": _months(s.get("month")),
                        "days": days})
    return {"name": tpl.get("name") or "", "utility": tpl.get("electricCompany") or "",
            "cloud_updated": tpl.get("updateTime") or "", "rate_unit": RATE_UNIT,
            "seasons": seasons}


def _day_on(sched: dict, day: dt.date) -> dict | None:
    for s in sched.get("seasons") or []:
        if day.month not in s["months"]:
            continue
        for d in s["days"]:
            if day.weekday() in d["weekdays"]:
                return d
    return None


def blocks_on(sched: dict, day: dt.date) -> list[dict]:
    """The blocks the aGate runs on ``day``: its season, then its day type."""
    d = _day_on(sched, day)
    return d["blocks"] if d else []


def blocks_with_rates(sched: dict, day: dt.date) -> list[dict]:
    """``blocks_on`` with each block's buy and sell rate for that day type (None when the
    cloud gives none, as in a copy taken before rates were kept)."""
    d = _day_on(sched, day)
    if not d:
        return []
    rates = d.get("rates") or {}
    return [{**b, "buy": (rates.get(b["wave"]) or {}).get("buy"),
             "sell": (rates.get(b["wave"]) or {}).get("sell")} for b in d["blocks"]]


def _digest(sched: dict) -> str:
    return hashlib.sha256(json.dumps(sched, sort_keys=True).encode()).hexdigest()


def is_tou(mode: str | None) -> bool:
    m = "".join(ch for ch in (mode or "").lower() if ch.isalpha())
    return m in ("timeofuse", "tou")


def sync_reason(mode: str | None, prev_mode: str | None, synced: bool,
                last_try: float | None = None, now: float | None = None) -> str | None:
    """Why to take a copy now: ``start`` on the first cloud pass, ``tou-mode`` when the
    mode has just become TOU, ``daily`` a day after the last read (``last_try``), else
    None."""
    if not synced:
        return "start"
    if is_tou(mode) and not is_tou(prev_mode):
        return "tou-mode"
    if last_try is not None and now is not None and now - last_try >= DAILY_S:
        return "daily"
    return None


def read(settings, serial: str) -> dict:
    """One cloud read of the TOU schedule (``get_tou_dispatch_detail``) for the aGate
    ``serial``, on the login the status loop shares. Raises on a failure; the caller
    reports it."""
    import asyncio

    from . import cloud_status

    async def _run():
        async with await cloud_status._client_for(
                settings.fwh_cloud_email, settings.fwh_cloud_password,
                serial, source="tou") as cloud:
            return await cloud.get_tou_dispatch_detail()

    data = asyncio.run(_run())
    if not isinstance(data, dict) or data.get("code") != 200 or not data.get("result"):
        raise RuntimeError(f"the cloud returned no TOU schedule: "
                           f"{(data or {}).get('message') if isinstance(data, dict) else data}")
    return data["result"]


def _record(row: dict | None, changed: bool | None = None) -> dict | None:
    if row is None:
        return None
    out = {k: row[k] for k in ("id", "gateway_id", "first_ts", "checked_ts",
                               "cloud_updated", "reason")}
    out["schedule"] = json.loads(row["body"])
    if changed is not None:
        out["changed"] = changed
    return out


def sync(store, settings, gateway_id: str, serial: str, reason: str,
         now: float | None = None) -> dict:
    """Read the schedule and keep a copy if it changed. Returns the latest copy, with
    ``changed``."""
    sched = schedule(read(settings, serial))
    row, changed = store.save_cloud_tou(gateway_id, now if now is not None else time.time(),
                                        sched["cloud_updated"], _digest(sched), reason,
                                        json.dumps(sched))
    return _record(row, changed)


def latest(store, gateway_id: str) -> dict | None:
    return _record(store.latest_cloud_tou(gateway_id))


def _runs(sched: dict, now: dt.datetime, days: int = 2) -> list[dict]:
    """Today's and the next days' blocks with rates, as aware start and end times."""
    out = []
    for i in range(days):
        day = now.date() + dt.timedelta(days=i)
        base = dt.datetime.combine(day, dt.time(), tzinfo=now.tzinfo)
        for b in blocks_with_rates(sched, day):
            s, e = _span(b)
            out.append({**b, "_s": base + dt.timedelta(minutes=s),
                        "_e": base + dt.timedelta(minutes=e)})
    return out


def ha_payload(copy: dict | None, now: dt.datetime) -> dict | None:
    """Home Assistant's TOU entities from the latest copy (#421), no cloud read: the
    schedule, the dispatch and tariff band now (with their times and rates), and the next
    change of each. None without a copy."""
    if not copy:
        return None
    sched = copy["schedule"]
    runs = _runs(sched, now)
    cur = next((r for r in runs if r["_s"] <= now < r["_e"]), None)
    out: dict[str, Any] = {
        "schedule": sched.get("name") or "Unnamed schedule", "utility": sched.get("utility") or "",
        "cloud_updated": sched.get("cloud_updated") or "",
        "checked": dt.datetime.fromtimestamp(copy.get("checked_ts") or 0, now.tzinfo).isoformat(),
        "rate_unit": sched.get("rate_unit") or RATE_UNIT,
        "today": [{k: v for k, v in b.items() if not k.startswith("_")}
                  for b in runs if b["_s"].date() == now.date()]}
    for kind, field in (("dispatch", "dispatch"), ("tariff", "wave")):
        nxt = None
        if cur is not None:
            nxt = next((r for r in runs if r["_s"] >= cur["_e"] and r[field] != cur[field]),
                       None)
        for when, r in (("now", cur), ("next", nxt)):
            key = f"{kind}_{when}"
            out[key] = (r[field] or None) if r else None
            out[f"{key}_start"] = r["_s"].isoformat() if r else None
            if kind == "dispatch" or when == "now":
                out[f"{key}_end"] = r["_e"].isoformat() if r else None
            if kind == "tariff":
                out[f"{key}_buy"] = r["buy"] if r else None
                out[f"{key}_sell"] = r["sell"] if r else None
    return out


def _hhmm(m: int) -> str:
    return f"{m // 60 % 24:02d}:{m % 60:02d}" if m < 24 * 60 else "24:00"


def _span(b: dict) -> tuple[int, int]:
    s, e = scheduler._minutes(b["start"]) or 0, scheduler._minutes(b["end"])
    return s, (24 * 60 if not e else e)


def _repeats(e: dict) -> str:
    tt = e.get("trigger_type") or "daily"
    if tt == "interval":
        return f"every {int(e.get('interval_min') or 0)} min"
    if tt == "cron":
        return f"cron {e.get('cron') or ''}".strip()
    return ""


def conflicts(sched: dict, entries: list[dict], now: dt.datetime,
              gateway_id: str) -> list[dict]:
    """Today's enabled Force schedules on this gateway (or All gateways) whose direction
    contradicts a TOU block they run in: one row per schedule and block, from the first
    to the last minute they share, with how many runs (``slots``) that covers."""
    blocks = blocks_on(sched, now.date())
    by_id = {e.get("id"): e for e in entries}
    tl = scheduler.timeline_segments(entries, now, gateway_id)
    rows: dict[tuple, dict] = {}
    for seg in tl["segments"] + tl.get("site", []):
        if seg["action"] != "force":
            continue
        e = by_id.get(seg["schedule_id"]) or {}
        force = ((e.get("action") or {}).get("direction") or "").lower()
        for s, en in seg["blocks"]:
            for bi, b in enumerate(blocks):
                want = TOU_BATTERY.get(b["dispatch_id"])
                if want is None or want == force:
                    continue
                bs, be = _span(b)
                lo, hi = max(s, bs), min(en, be)
                if lo >= hi:
                    continue
                key = (seg["schedule_id"], bi)
                r = rows.get(key)
                if r is None:
                    rows[key] = {"schedule_id": seg["schedule_id"], "name": seg["name"],
                                 "force": force, "repeats": _repeats(e),
                                 "tou_dispatch_id": b["dispatch_id"],
                                 "tou_dispatch": b["dispatch"], "_lo": lo, "_hi": hi,
                                 "slots": 1}
                else:
                    r["_lo"], r["_hi"] = min(r["_lo"], lo), max(r["_hi"], hi)
                    r["slots"] += 1
    out = []
    for r in sorted(rows.values(), key=lambda r: (r["_lo"], r["name"])):
        lo, hi = r.pop("_lo"), r.pop("_hi")
        out.append({**r, "start": _hhmm(lo), "end": _hhmm(hi)})
    return out


def import_plan(sched: dict, power_pct: float = 100) -> dict[str, list]:
    """Bridge schedules for the TOU blocks, for Self-Consumption as the base mode.

    ``entries``: one disabled Force schedule per block that charges, exports or holds the
    battery; the same block in several seasons or day types is one schedule when its days
    (or months) are the same, so it never runs on a day TOU doesn't. ``base``: blocks that
    Self-Consumption already does. ``left_out``: blocks with no bridge action (charging
    from solar only)."""
    groups: dict[tuple, list] = {}
    base, left_out = [], []
    for s in sched.get("seasons") or []:
        for d in s["days"]:
            for b in d["blocks"]:
                where = {**b, "season": s["name"], "day": d["name"]}
                if b["dispatch_id"] in BASE:
                    base.append(where)
                elif b["dispatch_id"] in FORCE:
                    key = (b["start"], b["end"], b["dispatch_id"])
                    groups.setdefault(key, []).append(
                        (frozenset(s["months"]), frozenset(d["weekdays"]), s["name"], d["name"]))
                else:
                    left_out.append(where)
    entries = []
    for (start, end, did), where in groups.items():
        merged: list[list] = []          # [months, days, labels]
        for months, days, sname, dname in where:
            for m in merged:
                if m[1] == days or m[0] == months:
                    m[0], m[1] = m[0] | months, m[1] | days
                    m[2].append((sname, dname))
                    break
            else:
                merged.append([months, days, [(sname, dname)]])
        s_min, e_min = _span({"start": start, "end": end})
        direction = FORCE[did]
        for months, days, labels in merged:
            action = {"kind": "force", "direction": direction, "unit": "pct"}
            if direction != "standby":
                action["power"] = power_pct
            where_txt = "; ".join(f"{a}, {b}" for a, b in labels)
            entries.append({
                "name": f"TOU {direction} {start}-{end} ({where_txt})",
                "enabled": False, "trigger_type": "daily", "fire_at": start,
                "duration_min": e_min - s_min,
                "days": [] if len(days) == 7 else sorted(days),
                "months": [] if len(months) == 12 else sorted(months),
                "action": action})
    return {"entries": entries, "base": base, "left_out": left_out}
