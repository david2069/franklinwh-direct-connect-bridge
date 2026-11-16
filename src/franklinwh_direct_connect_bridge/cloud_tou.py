"""The FranklinWH TOU schedule, from the Cloud API (owner 2026-11-16).

The aGate runs the TOU schedule set in the FranklinWH app; the local API can't read it
(1408 returns no timers), so the bridge reads ``get_tou_dispatch_detail`` and keeps a
dated copy: at start-up (the first good cloud pass) and whenever TOU mode is set, and on
**Sync now**. A copy is stored only when the schedule changed; otherwise the latest copy's
``checked_ts`` moves on.

While TOU mode is on, the aGate follows those blocks, so a bridge schedule that sets the
mode, forces the battery, changes the reserve or goes off-grid in the same minutes works
against them: ``conflicts`` lists those.

The bridge recommends its own schedules over FranklinWH TOU. TOU's one advantage is that
it runs without the bridge, which is also its drawback: the bridge can't see, condition or
notify on it. ``import_plan`` turns the TOU blocks into bridge schedules, created disabled,
for Self-Consumption as the base mode. Nothing is ever written to the cloud or the aGate.
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
#: dayType → weekdays (0 = Monday), as the library's ``_match_day_type``.
DAY_TYPE = {1: [0, 1, 2, 3, 4], 2: [5, 6], 3: [0, 1, 2, 3, 4, 5, 6]}

#: The bridge's base mode after an import is Self-Consumption: these need no schedule.
BASE = {1, 6}
#: TOU dispatches with a bridge action: Force charge, discharge, standby.
FORCE = {8: "charge", 7: "discharge", 2: "standby"}
#: Schedule actions that work against a TOU block (the battery, the mode, the reserve).
CLASH_KINDS = ("set_mode", "force", "reserve_soc", "offgrid")


def _months(text: Any) -> list[int]:
    out = []
    for p in str(text or "").split(","):
        try:
            out.append(int(p))
        except ValueError:
            continue
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
                         "weekdays": DAY_TYPE.get(d.get("dayType"), []), "blocks": blocks})
        seasons.append({"name": s.get("seasonName") or "", "months": _months(s.get("month")),
                        "days": days})
    return {"name": tpl.get("name") or "", "utility": tpl.get("electricCompany") or "",
            "cloud_updated": tpl.get("updateTime") or "", "seasons": seasons}


def blocks_on(sched: dict, day: dt.date) -> list[dict]:
    """The blocks the aGate runs on ``day``: its season, then its day type."""
    for s in sched.get("seasons") or []:
        if day.month not in s["months"]:
            continue
        for d in s["days"]:
            if day.weekday() in d["weekdays"]:
                return d["blocks"]
    return []


def _digest(sched: dict) -> str:
    return hashlib.sha256(json.dumps(sched, sort_keys=True).encode()).hexdigest()


def is_tou(mode: str | None) -> bool:
    m = "".join(ch for ch in (mode or "").lower() if ch.isalpha())
    return m in ("timeofuse", "tou")


def sync_reason(mode: str | None, prev_mode: str | None, synced: bool) -> str | None:
    """Why to take a copy now: ``start`` on the first cloud pass, ``tou-mode`` when the
    mode has just become TOU, else None."""
    if not synced:
        return "start"
    if is_tou(mode) and not is_tou(prev_mode):
        return "tou-mode"
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


def _hhmm(m: int) -> str:
    return f"{m // 60 % 24:02d}:{m % 60:02d}" if m < 24 * 60 else "24:00"


def _span(b: dict) -> tuple[int, int]:
    s, e = scheduler._minutes(b["start"]) or 0, scheduler._minutes(b["end"])
    return s, (24 * 60 if not e else e)


def conflicts(sched: dict, entries: list[dict], now: dt.datetime,
              gateway_id: str) -> list[dict]:
    """Today's enabled schedules on this gateway (or All gateways) whose action works
    against a TOU block, with the minutes they share."""
    blocks = blocks_on(sched, now.date())
    tl = scheduler.timeline_segments(entries, now, gateway_id)
    out: dict[str, dict] = {}
    for seg in tl["segments"] + tl.get("site", []):
        if seg["action"] not in CLASH_KINDS:
            continue
        for s, e in seg["blocks"]:
            for b in blocks:
                bs, be = _span(b)
                lo, hi = max(s, bs), min(e, be)
                if lo >= hi:
                    continue
                c = out.setdefault(seg["schedule_id"], {
                    "schedule_id": seg["schedule_id"], "name": seg["name"],
                    "action": seg["action"], "overlaps": []})
                c["overlaps"].append({"start": _hhmm(lo), "end": _hhmm(hi),
                                      "dispatch_id": b["dispatch_id"],
                                      "dispatch": b["dispatch"]})
    return list(out.values())


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
