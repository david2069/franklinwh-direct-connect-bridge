"""Tariff plans per meter (owner 2026-11-13; same rules as the Modbus Bridge).

A meter has at most one tariff in force on any day. A tariff's dates are inclusive ISO
days; a blank start is "since always", a blank end is "current". Adding a current tariff
(no end) closes the meter's current one the day before it starts; any other overlap is
refused. The meter points at the tariff in force today, so pricing follows the dates."""
from __future__ import annotations

import datetime as dt


class Overlap(ValueError):
    """Two tariffs of one meter would be in force on the same day."""


def today() -> dt.date:
    return dt.date.today()


def _d(s) -> dt.date | None:
    return dt.date.fromisoformat(s) if s else None


def _covers(t: dict, day: dt.date) -> bool:
    s, e = _d(t.get("effective_start")), _d(t.get("effective_end"))
    return (s is None or s <= day) and (e is None or day <= e)


def _overlaps(a_start, a_end, b: dict) -> bool:
    lo = max(a_start or dt.date.min, _d(b.get("effective_start")) or dt.date.min)
    hi = min(a_end or dt.date.max, _d(b.get("effective_end")) or dt.date.max)
    return lo <= hi


def of_meter(store, meter_id: str) -> list[dict]:
    return [t for t in store.tariffs() if t.get("meter_id") == meter_id]


def in_force(store, meter_id: str, day: dt.date | None = None) -> dict | None:
    day = day or today()
    return next((t for t in of_meter(store, meter_id) if _covers(t, day)), None)


def current(store, meter_id: str) -> dict | None:
    """The meter's open-ended tariff (no end date), if any."""
    return next((t for t in of_meter(store, meter_id) if not t.get("effective_end")), None)


def plan(store, meter_id: str, start: str | None, end: str | None,
         exclude: str | None = None, adding: bool = True) -> dict:
    """What adding (``adding``) or re-dating a tariff with these dates does: the start it
    gets, the current tariff it closes and when, or Overlap. Changes nothing. Re-dating
    never closes another tariff: it must fit."""
    others = [t for t in of_meter(store, meter_id) if t["id"] != exclude]
    cur = next((t for t in others if not t.get("effective_end")), None) if adding else None
    if not start and not end and cur is not None:
        start = today().isoformat()        # a new plan replaces the current one from today
    s, e = _d(start), _d(end)
    close = None
    if e is None and cur is not None and s is not None and (
            _d(cur.get("effective_start")) or dt.date.min) < s:
        close = {"id": cur["id"], "name": cur.get("name") or cur["id"],
                 "end": (s - dt.timedelta(days=1)).isoformat()}
    for t in others:
        t_end = close["end"] if close and t["id"] == close["id"] else t.get("effective_end")
        if _overlaps(s, e, {**t, "effective_end": t_end}):
            raise Overlap(f"overlaps \"{t.get('name') or t['id']}\" "
                          f"({t.get('effective_start') or '…'} → {t_end or 'current'}) on this "
                          "meter: one tariff is in force per meter per day")
    return {"start": start, "end": end, "close": close}


def apply(store, meter_id: str, p: dict) -> None:
    """Close what plan() said to close, then point the meter at today's tariff."""
    c = p.get("close")
    if c:
        t = store.tariff(c["id"])
        store.set_tariff_dates(c["id"], t.get("effective_start"), c["end"])
    repoint(store, meter_id)


def repoint(store, meter_id: str | None) -> None:
    if not meter_id or store.meter(meter_id) is None:
        return
    t = in_force(store, meter_id)
    store.set_meter_plan(meter_id, t.get("utility_id") if t else None, t["id"] if t else None)
