"""Schedule engine — time windows that run local actions and HA actions.

Modelled on the Modbus Bridge's Schedule & Automations page, with one honest
difference recorded up front:

  **Force charge / discharge / standby are SunSpec/Modbus controls with no
  Direct-Connect equivalent.** They are offered here only when the bridge's own
  direct-Modbus path (``battery_control``, the proven ``franklinwh-modbus`` library)
  is reachable — the same path the dashboard Battery Control widget uses, independent
  of the modbus-bridge service. When Modbus is unreachable the action is listed with
  the reason rather than firing blind. Everything else — operating mode, smart
  circuits, off-grid — runs over the local channel and is hardware-verified. A
  reserve-SoC action is offered only when a cloud provider is configured, because
  the local write does not work (see BACKLOG RESEARCH-RESERVE-SOC).

Offering a control that silently does nothing is worse than not offering it, so
unavailable actions are listed with the reason instead of being hidden or faked.
"""

from __future__ import annotations

import datetime as dt
import fnmatch
import re
from typing import Any

from . import ha_instances

#: Local actions that are hardware-verified. Anything not here is not offered.
ACTIONS: dict[str, dict[str, Any]] = {
    "set_mode": {
        "label": "Set operating mode",
        "params": ["mode"],           # tou | self | backup, or a programme id
        "note": "1727 opt:3 — verified.",
    },
    "smart_circuit": {
        "label": "Smart circuit on/off",
        "params": ["circuit", "on"],
        "note": "1409 full-block RMW with read-back — verified 2026-08-08.",
    },
    "offgrid": {
        "label": "Go off-grid / reconnect",
        "params": ["on", "soc"],
        "note": "1723 — consequential; confirm before enabling a schedule that uses it.",
    },
    "reserve_soc": {
        "label": "Set reserve SoC",
        "params": ["mode", "soc"],
        "requires_provider": "cloud",
        "note": "No local write path exists; needs cloud credentials.",
    },
    "notify": {
        "label": "Notify (Home Assistant)",
        "params": ["device_id", "title", "message"],
        "note": "Sends through a configured notification device.",
    },
    "force": {
        "label": "Force charge / discharge / standby",
        "params": ["direction", "power", "unit", "target_soc"],
        "requires": "modbus",
        "note": "Direct Modbus/SunSpec WSet. Runs for the schedule window and "
                "auto-releases at window end; enforces target SoC if set.",
    },
}

#: Deliberately absent, with the reason — see the module docstring.
UNAVAILABLE: dict[str, str] = {
    # Force charge/discharge/standby moved OUT of here — the direct-Modbus path
    # (battery_control) now provides them, offered when Modbus is reachable.
    "smart_circuit_schedule": "the gateway accepts and discards schedule writes",
}

#: The gate's operators — ported from the Modbus bridge so a condition authored
#: there evaluates identically here. Simple comparisons, plus inclusive ranges,
#: numeric membership, verbatim name lists, and case-insensitive wildcards.
OPERATORS: tuple[str, ...] = (
    "<", "<=", "==", "!=", ">=", ">", "between",
    "in", "not_in", "matchlist", "not_matchlist", "like", "not_like",
)
#: Ops whose RHS is a raw member-list / pattern, so the Value|Lookup toggle is
#: meaningless and hidden for them.
TEXT_RHS_OPERATORS: frozenset[str] = frozenset(
    {"in", "not_in", "matchlist", "not_matchlist", "like", "not_like"})

MATCH_ALL = "all"
MATCH_ANY = "any"


def _coerce_number(v: Any) -> float | None:
    """A number, or None. Bools are NOT numbers — True must not read as 1 in a
    numeric comparison, or ``mode == 1`` style bugs creep in."""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return None


def _eq(a: Any, b: Any) -> bool:
    """Equality that compares numerically when both sides are numbers, exactly
    for bools, and case-insensitively for names/enums otherwise."""
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    na, nb = _coerce_number(a), _coerce_number(b)
    if na is not None and nb is not None:
        return na == nb
    return str(a).casefold() == str(b).casefold()


def _as_ranges(spec: Any) -> list[tuple[float, float]]:
    """Members for ``in``/``not_in``: a scalar becomes a point range; ``a-b`` or
    ``a..b`` (en/em dash accepted) becomes an inclusive range, order-independent.
    Non-numeric members drop out; an empty result matches nothing."""
    toks = list(spec) if isinstance(spec, (list, tuple)) \
        else re.split(r"[,;\n]", str(spec or ""))
    out: list[tuple[float, float]] = []
    for tok in toks:
        s = str(tok).strip()
        if not s:
            continue
        m = re.match(r"^(-?\d+(?:\.\d+)?)\s*(?:\.\.|[-–—])\s*(-?\d+(?:\.\d+)?)$", s)
        if m:
            lo, hi = float(m.group(1)), float(m.group(2))
            out.append((min(lo, hi), max(lo, hi)))
        else:
            n = _coerce_number(s)
            if n is not None:
                out.append((n, n))
    return out


def _text_members(spec: Any) -> list[str]:
    """Members for ``matchlist``: verbatim names, case-folded, no range parsing
    (so ``Self-Consumption`` stays one name)."""
    toks = list(spec) if isinstance(spec, (list, tuple)) \
        else re.split(r"[,;\n]", str(spec or ""))
    return [str(t).strip().casefold() for t in toks if str(t).strip()]


def _like(live: Any, pattern: Any) -> bool:
    """Case-insensitive wildcard: ``*``/``%`` = many, ``?``/``_`` = one. A pattern
    with no wildcard falls back to a substring test."""
    p = str(pattern).replace("%", "*").replace("_", "?").casefold()
    text = str(live).casefold()
    if any(c in p for c in "*?"):
        return fnmatch.fnmatch(text, p)
    return p in text


def _apply_op(op: str, live: Any, value: Any, value2: Any = None) -> bool:
    """One leaf comparison. A missing/None live value is FALSE for EVERY operator
    (including ``!=``): a scheduler must never act on data it does not have."""
    if live is None:
        return False
    if op == "==":
        return _eq(live, value)
    if op == "!=":
        return not _eq(live, value)
    if op in ("<", "<=", ">", ">="):
        lv, rv = _coerce_number(live), _coerce_number(value)
        if lv is None or rv is None:
            return False
        return {"<": lv < rv, "<=": lv <= rv, ">": lv > rv, ">=": lv >= rv}[op]
    if op == "between":
        lv, rv, rv2 = _coerce_number(live), _coerce_number(value), _coerce_number(value2)
        if lv is None or rv is None or rv2 is None:
            return False
        lo, hi = sorted((rv, rv2))
        return lo <= lv <= hi
    if op in ("in", "not_in"):
        lv = _coerce_number(live)
        hit = lv is not None and any(lo <= lv <= hi for lo, hi in _as_ranges(value))
        return hit if op == "in" else not hit
    if op in ("matchlist", "not_matchlist"):
        hit = str(live).casefold() in _text_members(value)
        return hit if op == "matchlist" else not hit
    if op in ("like", "not_like"):
        hit = _like(live, value)
        return hit if op == "like" else not hit
    return False

_VAR = re.compile(r"%([a-zA-Z0-9_.]+)%")


def substitute(text: str, snapshot: dict) -> str:
    """Replace ``%sensor.id%`` with live values.

    An unreadable value renders as ``?`` rather than blocking the message: a
    notification that arrives with one field missing is far more useful than one
    that never arrives because a sensor was briefly unavailable.
    """
    def repl(m: re.Match) -> str:
        val = snapshot.get(m.group(1))
        return "?" if val is None else str(val)
    return _VAR.sub(repl, text or "")


def _is_tree(node: dict) -> bool:
    """A node is a GROUP if it carries nested conditions (or a match), else a
    leaf ROW. Matches the Modbus bridge's shape so trees port verbatim."""
    return "conditions" in node or "match" in node


def _eval_node(node: dict, snapshot: dict, trace: list | None) -> bool:
    if _is_tree(node):
        return _eval_tree(node.get("conditions") or [], snapshot,
                          node.get("match", MATCH_ALL), trace)
    op = node.get("op", "==")
    live = snapshot.get(node.get("sensor"))
    if node.get("value_kind") == "sensor":
        # Lookup: compare to another sensor's live value; an absent RHS fails
        # closed exactly like an absent LHS.
        resolved = snapshot.get(node.get("value_sensor"))
        result = False if resolved is None else _apply_op(op, live, resolved)
    else:
        resolved = node.get("value")
        result = _apply_op(op, live, resolved, node.get("value2"))
    if trace is not None:
        row = {"sensor": node.get("sensor"), "op": op, "value": resolved,
               "live_value": live, "result": result}
        if node.get("value_kind") == "sensor":
            row["value_kind"] = "sensor"
            row["value_sensor"] = node.get("value_sensor")
        if op == "between":
            row["value2"] = node.get("value2")
        if "cid" in node:
            row["cid"] = node["cid"]
        trace.append(row)
    return result


def _eval_tree(nodes: list[dict], snapshot: dict, match: str,
               trace: list | None) -> bool:
    # No short-circuit: every leaf is visited so Test Verification gets a full
    # trace. Vacuous truth — empty ALL is True, empty ANY is False.
    results = [_eval_node(n, snapshot, trace) for n in nodes]
    if str(match).lower() == MATCH_ANY:
        return any(results)
    return all(results)


def evaluate(rows: list[dict], snapshot: dict, match: str = "all",
             trace: list | None = None) -> bool:
    """Evaluate a condition tree against the live snapshot.

    Rows may nest into ALL/ANY groups; a flat list behaves exactly as before, so
    existing schedules are unaffected. A missing sensor (LHS or Lookup RHS) is
    FALSE — an absent reading must never fire an action. Pass ``trace`` (a list)
    to collect one entry per leaf for Test Verification.
    """
    if not rows:
        return True
    return _eval_tree(rows, snapshot, match, trace)


def _minutes(hhmm: str) -> int | None:
    try:
        h, m = str(hhmm).split(":")[:2]
        return int(h) * 60 + int(m)
    except (ValueError, AttributeError):
        return None


def _window_end_ts(entry: dict, now: dt.datetime) -> float:
    """Epoch seconds of THIS window's close (fire_at + duration on now's date; a window
    that wraps past midnight ends the next day). Used to persist a dispatch's deadline."""
    start_min = _minutes(entry.get("fire_at", "")) or 0
    dur = int(entry.get("duration_min") or 0)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return (midnight + dt.timedelta(minutes=start_min + dur)).timestamp()


#: The trigger types offered in the editor. Everything except interval/cron/always
#: resolves to one or more daily time windows (gated by the calendar restrictions).
TRIGGER_TYPES: tuple[str, ...] = (
    "window", "once", "daily", "weekly", "interval", "monthly", "cron", "always",
)


def cron_available() -> bool:
    try:
        import croniter  # noqa: F401
        return True
    except Exception:                                          # noqa: BLE001
        return False


def _windows_for(entry: dict) -> list[tuple[int, int]]:
    """Daily time window(s) as (start_min, duration_min). The 'window' trigger uses the
    user's list of start→end pairs (wrap past midnight ok); every other daily-family
    trigger is a single fire_at + duration window."""
    if (entry.get("trigger_type") or "daily") == "window":
        out: list[tuple[int, int]] = []
        for w in entry.get("windows") or []:
            s, e = _minutes(w.get("start", "")), _minutes(w.get("end", ""))
            if s is None or e is None:
                continue
            out.append((s, (e - s) if e > s else (e + 24 * 60 - s)))   # wrap
        if out:
            return out
    s = _minutes(entry.get("fire_at", "")) or 0
    return [(s, int(entry.get("duration_min") or 0))]


def _cur_inside(cur: int, start: int, dur: int) -> bool:
    """Is minute-of-day ``cur`` inside a window of ``dur`` minutes from ``start``?"""
    if dur <= 0:
        return cur == start
    end = start + dur
    if end <= 24 * 60:
        return start <= cur < end
    return cur >= start or cur < end - 24 * 60                  # wraps past midnight


def _occ_date(now: dt.datetime, start: int, dur: int, cur: int) -> dt.date:
    """The date a currently-open window OPENED on (its post-midnight tail belongs to the
    previous day)."""
    if dur > 0 and (start + dur) > 24 * 60 and cur < start and cur < (start + dur - 24 * 60):
        return now.date() - dt.timedelta(days=1)
    return now.date()


def _interval_window(entry: dict, now: dt.datetime):
    iv = int(entry.get("interval_min") or 0)
    if iv <= 0:
        return ("outside", None, None, now.date())
    dur = int(entry.get("duration_min") or 0)
    win = dur if dur > 0 else 1
    anchor_min = _minutes(entry.get("anchor", "")) or 0
    anchor_dt = now.replace(hour=0, minute=0, second=0, microsecond=0) + dt.timedelta(minutes=anchor_min)
    if now < anchor_dt:
        anchor_dt -= dt.timedelta(days=1)
    k = int((now - anchor_dt).total_seconds() // 60 // iv)
    slot = anchor_dt + dt.timedelta(minutes=k * iv)
    if (now - slot).total_seconds() / 60 < win:
        end = (slot + dt.timedelta(minutes=win)).timestamp()
        return ("inside", f"iv:{int(slot.timestamp())}", end, slot.date())
    return ("outside", None, None, now.date())


def _cron_window(entry: dict, now: dt.datetime):
    expr = (entry.get("cron") or "").strip()
    if not expr:
        return ("outside", None, None, now.date())
    try:
        from croniter import croniter
        if not croniter.is_valid(expr):
            return ("outside", None, None, now.date())
        prev = croniter(expr, now).get_prev(dt.datetime)
    except Exception:                                          # noqa: BLE001
        return ("outside", None, None, now.date())
    dur = int(entry.get("duration_min") or 0)
    win = dur if dur > 0 else 1
    if (now - prev).total_seconds() / 60 < win:
        end = (prev + dt.timedelta(minutes=win)).timestamp()
        return ("inside", f"cr:{int(prev.timestamp())}", end, prev.date())
    return ("outside", None, None, now.date())


def window_now(entry: dict, now: dt.datetime):
    """Is a window open at ``now``? Returns ``(state, key, window_end_ts, occ_date)``
    where ``state`` is 'inside'|'outside', ``key`` uniquely identifies the occurrence
    (for the fire-once guard), ``window_end_ts`` is the window's close epoch (None if
    open-ended), and ``occ_date`` is the date the occurrence belongs to.

    'always' has no time window (it is gated purely by entry conditions, handled in the
    tick); it reports 'inside' here so the tick can drive it from the conditions."""
    tt = entry.get("trigger_type") or "daily"
    if tt == "always":
        return ("inside", "always", None, now.date())
    if tt == "interval":
        return _interval_window(entry, now)
    if tt == "cron":
        return _cron_window(entry, now)
    cur = now.hour * 60 + now.minute
    for idx, (s, dur) in enumerate(_windows_for(entry)):
        if _cur_inside(cur, s, dur):
            d = _occ_date(now, s, dur, cur)
            end = ((dt.datetime.combine(d, dt.time.min) + dt.timedelta(minutes=s + dur)).timestamp()
                   if dur else None)
            key = d.isoformat() if idx == 0 else f"{d.isoformat()}#{idx}"   # idx0 = legacy date key
            return ("inside", key, end, d)
    return ("outside", None, None, now.date())


def window_state(entry: dict, now: dt.datetime) -> str:
    """``before`` | ``inside`` | ``after`` for a daily entry.

    Windows that cross midnight are handled: 22:00 for 300 minutes is inside at
    01:00 the next day, which a naive start<=now<end comparison gets wrong.
    """
    start = _minutes(entry.get("fire_at", "")) or 0
    dur = int(entry.get("duration_min") or 0)
    cur = now.hour * 60 + now.minute
    if dur <= 0:
        return "inside" if cur == start else ("before" if cur < start else "after")
    end = start + dur
    if end <= 24 * 60:
        return "inside" if start <= cur < end else ("before" if cur < start else "after")
    # wraps past midnight
    return "inside" if (cur >= start or cur < end - 24 * 60) else "before"


def _window_anchor_date(entry: dict, now: dt.datetime) -> dt.date:
    """The calendar date the CURRENT window occurrence started on. For a window that
    wraps past midnight (e.g. 22:00 for 300 min), the post-midnight tail belongs to the
    previous day — so recurrence is judged against the day the window opened, not the
    day the clock happens to read."""
    start = _minutes(entry.get("fire_at", "")) or 0
    dur = int(entry.get("duration_min") or 0)
    cur = now.hour * 60 + now.minute
    if dur > 0 and (start + dur) > 24 * 60 and cur < start and cur < (start + dur - 24 * 60):
        return now.date() - dt.timedelta(days=1)
    return now.date()


def _calendar_ok(entry: dict, d: dt.date) -> tuple[bool, str]:
    """Does the entry's recurrence permit firing on date ``d``? Every recurrence field is
    a RESTRICTION; absent/empty means 'no restriction' (fires every day, as before).
    Returns ``(ok, reason)``."""
    sd, ed = entry.get("start_date"), entry.get("end_date")
    if sd:
        try:
            if d < dt.date.fromisoformat(sd):
                return False, f"before start date {sd}"
        except ValueError:
            pass
    if ed:
        try:
            if d > dt.date.fromisoformat(ed):
                return False, f"after end date {ed}"
        except ValueError:
            pass
    days = entry.get("days") or []
    if days and d.weekday() not in days:
        return False, "not one of its days of the week"
    months = entry.get("months") or []
    if months and d.month not in months:
        return False, "not one of its months"
    dom = entry.get("day_of_month")
    if dom:
        import calendar as _cal
        last = _cal.monthrange(d.year, d.month)[1]
        if d.day != min(int(dom), last):          # clamp: 31 -> 30/28 at month end
            return False, "not its day of the month"
    return True, "recurrence ok"


def next_fire_ts(entry: dict, now: dt.datetime, last_fired_day: str | None = None):
    """Epoch seconds of the next time this entry's WINDOW opens per its recurrence
    (runtime conditions aside). None if disabled, or never within a year (e.g. past
    its end_date). Searches up to 366 days ahead."""
    if not entry.get("enabled"):
        return None
    tt = entry.get("trigger_type") or "daily"
    if tt == "always":
        return None                                        # continuous; no scheduled fire
    if tt == "interval":
        iv = int(entry.get("interval_min") or 0)
        if iv <= 0:
            return None
        anchor_min = _minutes(entry.get("anchor", "")) or 0
        anchor_dt = now.replace(hour=0, minute=0, second=0, microsecond=0) + dt.timedelta(minutes=anchor_min)
        if now < anchor_dt:
            anchor_dt -= dt.timedelta(days=1)
        k = int((now - anchor_dt).total_seconds() // 60 // iv) + 1
        return (anchor_dt + dt.timedelta(minutes=k * iv)).timestamp()
    if tt == "cron":
        try:
            from croniter import croniter
            expr = (entry.get("cron") or "").strip()
            if croniter.is_valid(expr):
                return croniter(expr, now).get_next(dt.datetime).timestamp()
        except Exception:                                  # noqa: BLE001
            pass
        return None
    # daily-family: earliest upcoming window start over the next year.
    wins = _windows_for(entry)
    for i in range(0, 367):
        d = now.date() + dt.timedelta(days=i)
        if not _calendar_ok(entry, d)[0]:
            continue
        best = None
        for idx, (s_min, dur) in enumerate(wins):
            fire_dt = dt.datetime.combine(d, dt.time.min) + dt.timedelta(minutes=s_min)
            key = d.isoformat() if idx == 0 else f"{d.isoformat()}#{idx}"
            if i == 0:
                if last_fired_day == key:
                    continue
                end = fire_dt + dt.timedelta(minutes=dur) if dur else fire_dt
                if now >= end:
                    continue
            if best is None or fire_dt < best:
                best = fire_dt
        if best is not None:
            return best.timestamp()
    return None


def active_now(entry: dict, now: dt.datetime, last_fired_day: str | None = None) -> bool:
    """A proxy for 'running now': enabled, inside the current window, and already fired
    this occurrence. 'always' is continuous (determined at tick time) -> reported False
    here. (Runtime conditions/dispatch state aside.)"""
    if not entry.get("enabled"):
        return False
    if (entry.get("trigger_type") or "daily") == "always":
        return False
    state, key, _end, occ_date = window_now(entry, now)
    if state != "inside" or not _calendar_ok(entry, occ_date)[0]:
        return False
    return last_fired_day == key


def due(entry: dict, now: dt.datetime, snapshot: dict,
        last_fired_day: str | None) -> tuple[bool, str]:
    """Should this entry fire now? Returns ``(fire, reason)``.

    The reason is returned whether or not it fires, so the UI can say *why* an
    entry did nothing — the usual complaint about schedulers.
    """
    if not entry.get("enabled"):
        return False, "disabled"
    state, key, _end, occ_date = window_now(entry, now)
    if state != "inside":
        return False, "outside its window"
    cal_ok, cal_reason = _calendar_ok(entry, occ_date)
    if not cal_ok:
        return False, cal_reason
    # Fire once per occurrence (a date for daily-family, a slot/cron ts otherwise). The
    # 'always' trigger has no occurrence — its rising edge is handled in the tick.
    if (entry.get("trigger_type") or "daily") != "always" and last_fired_day == key:
        return False, "already fired this occurrence"
    if not evaluate(entry.get("conditions") or [],
                    snapshot, entry.get("match", "all")):
        return False, "entry conditions not met"
    return True, "conditions met"


EXPORT_TYPE = "franklinwh-local-schedules"
EXPORT_VERSION = 1

#: Built-in schedule templates. Every action here is hardware-verified on the
#: local channel — no force-charge presets, because the local protocol cannot do
#: that (see UNAVAILABLE). A preset is loaded into the editor, not fired blind.
PRESETS: list[dict[str, Any]] = [
    {"id": "self_consumption", "name": "Self-Consumption all day",
     "description": "Switch to Self-Consumption at midnight.",
     "spec": {"fire_at": "00:00", "duration_min": 0,
              "action": {"kind": "set_mode", "mode": "self"}}},
    {"id": "tou_evening", "name": "Time-of-Use in the evening",
     "description": "Switch to Time-of-Use at 15:00 for the peak window.",
     "spec": {"fire_at": "15:00", "duration_min": 0,
              "action": {"kind": "set_mode", "mode": "tou"}}},
    {"id": "backup_storm", "name": "Emergency Backup (storm)",
     "description": "Switch to Emergency Backup — hold charge for an outage.",
     "spec": {"fire_at": "18:00", "duration_min": 0,
              "action": {"kind": "set_mode", "mode": "backup"}}},
    {"id": "circuit_evening_off", "name": "Turn a circuit off overnight",
     "description": "Smart circuit 1 off at 23:00. Change the circuit to suit.",
     "spec": {"fire_at": "23:00", "duration_min": 0,
              "action": {"kind": "smart_circuit", "circuit": 1, "on": False}}},
    {"id": "low_soc_alert", "name": "Low battery alert (notify only)",
     "description": "Notify when SoC drops below 20% — no battery action.",
     "spec": {"fire_at": "00:00", "duration_min": 1439, "match": "all",
              "conditions": [{"sensor": "battery.soc_pct", "op": "<", "value": 20}],
              "action": {"kind": ""},
              "ha_actions": [{"device_id": "", "title": "FranklinWH",
                              "message": "Battery low: %battery.soc_pct%%"}]}},
    {"id": "peak_window_notify", "name": "Peak window — notify start & end",
     "description": "During the 16:00–21:00 peak, notify when it starts and ends, "
                    "with the live SoC. No battery action — pure awareness.",
     "spec": {"fire_at": "16:00", "duration_min": 300, "action": {"kind": ""},
              "ha_actions": [{"device_id": "", "when": "both", "title": "Peak window",
                              "message": "Peak %mode.name% — SoC %battery.soc_pct%%, "
                                         "grid %grid.power_w%W"}]}},
    {"id": "tou_if_charged", "name": "Time-of-Use at peak (only if charged)",
     "description": "Switch to Time-of-Use at 16:00 — but only if SoC is above 50%, so "
                    "a near-empty battery is left in Self-Consumption. Shows a condition gate.",
     "spec": {"fire_at": "16:00", "duration_min": 0, "match": "all",
              "conditions": [{"sensor": "battery.soc_pct", "op": ">", "value": 50}],
              "action": {"kind": "set_mode", "mode": "tou"}}},

    # ── Dispatch templates (require Modbus — force charge/discharge via M704 WSet). Ported
    #    from the Modbus bridge's grid-programme presets. Loaded into the editor for review;
    #    the force auto-releases at the window's end and honours the target-SoC guard. ──
    {"id": "peak_shave", "name": "Peak shaving (discharge at peak)", "requires": "modbus",
     "description": "Force-discharge across the 16:00–21:00 peak to cover the home from "
                    "battery — but only while SoC is above 30%, holding a 20% floor.",
     "spec": {"fire_at": "16:00", "duration_min": 300, "match": "all",
              "conditions": [{"sensor": "battery.soc_pct", "op": ">", "value": 30}],
              "action": {"kind": "force", "direction": "discharge", "unit": "pct",
                         "power": 100, "target_soc": 20}}},
    {"id": "export_bonus", "name": "Battery Bonus export (evening)", "requires": "modbus",
     "description": "Force-discharge to the grid during an evening bonus window when the "
                    "battery is well charged (SoC ≥ 50%), holding a 30% floor.",
     "spec": {"fire_at": "18:00", "duration_min": 180, "match": "all",
              "conditions": [{"sensor": "battery.soc_pct", "op": ">=", "value": 50}],
              "action": {"kind": "force", "direction": "discharge", "unit": "pct",
                         "power": 100, "target_soc": 30}}},
    {"id": "solar_sponge", "name": "Solar sponge (charge midday)", "requires": "modbus",
     "description": "Force-charge from midday solar (11:00–15:00) while there's headroom "
                    "(SoC < 80%), soaking up excess PV before the evening.",
     "spec": {"fire_at": "11:00", "duration_min": 240, "match": "all",
              "conditions": [{"sensor": "battery.soc_pct", "op": "<", "value": 80}],
              "action": {"kind": "force", "direction": "charge", "unit": "pct",
                         "power": 100, "target_soc": 100}}},
    {"id": "offpeak_charge", "name": "Off-peak charge (overnight)", "requires": "modbus",
     "description": "Force-charge overnight (01:00–06:00) on cheap tariff, but only if the "
                    "battery is below 50%, topping up to a 90% target.",
     "spec": {"fire_at": "01:00", "duration_min": 300, "match": "all",
              "conditions": [{"sensor": "battery.soc_pct", "op": "<", "value": 50}],
              "action": {"kind": "force", "direction": "charge", "unit": "pct",
                         "power": 100, "target_soc": 90}}},
]


def preset(preset_id: str) -> dict | None:
    return next((p for p in PRESETS if p["id"] == preset_id), None)


#: Fields carried across an export/import — the whole spec plus name/enabled.
_PORTABLE_KEYS = ("name", "enabled", "fire_at", "duration_min", "match",
                  "entry_hold_s", "gateway_id", "conditions", "exit_conditions",
                  "exit_match", "action", "ha_actions",
                  "days", "months", "day_of_month", "start_date", "end_date", "priority", "conflict",
                  "trigger_type", "windows", "interval_min", "anchor", "cron")


def portable(entry: dict) -> dict[str, Any]:
    """A schedule reduced to what travels — no ids, no last_fired state."""
    return {k: entry.get(k) for k in _PORTABLE_KEYS if k in entry}


# ── cross-bridge import: the Modbus bridge's "franklinwh-automations" bundle ───
#: The Modbus/other bridge's export type we can read + map to our schema.
IMPORT_TYPE_AUTOMATIONS = "franklinwh-automations"

#: Modbus action string → our (kind, direction) for the force family.
_AUTOMATION_FORCE = {
    "force_charge": "charge", "force_discharge": "discharge", "force_standby": "standby",
}


def _map_conditions(nodes) -> list:
    """Map a foreign condition list (leaves + nested ALL/ANY groups) to ours. Match words
    are lower-cased; leaves keep sensor/op/value/value2 verbatim (unknown sensors are
    flagged, not dropped, by validate_import)."""
    out = []
    for n in nodes or []:
        if not isinstance(n, dict):
            continue
        if "conditions" in n or "match" in n:            # nested group
            out.append({
                "match": str(n.get("match", "all")).lower(),
                "conditions": _map_conditions(n.get("conditions")),
            })
        else:                                            # leaf comparison
            leaf = {"sensor": n.get("sensor"), "op": n.get("op"), "value": n.get("value")}
            if "value2" in n:
                leaf["value2"] = n.get("value2")
            out.append(leaf)
    return out


def _map_automation_action(act, params: dict) -> dict:
    """Map a foreign action (string kind + params) to our action object."""
    params = params or {}
    a = (act or "").lower()
    if a in _AUTOMATION_FORCE:
        unit = "pct" if params.get("power_pct") is not None else "w"
        return {"kind": "force", "direction": _AUTOMATION_FORCE[a], "unit": unit,
                "power": params.get("power_pct") if unit == "pct" else params.get("power_w") or 0,
                "target_soc": params.get("target_soc") or 0}
    if a in ("set_mode", "mode"):
        return {"kind": "set_mode", "mode": params.get("mode") or params.get("value") or "self"}
    if a in ("reserve_self", "reserve_tou"):
        return {"kind": "reserve_soc", "mode": "self" if a == "reserve_self" else "tou",
                "soc": params.get("pct") if params.get("pct") is not None else params.get("soc") or 0}
    # release / none / unknown → no direct action (the window/exit handles release)
    return {"kind": ""}


#: Foreign trigger_kind → our trigger_type (unknowns fall through to daily).
_AUTOMATION_TRIGGER = {
    "daily": "daily", "always": "always", "window": "window", "interval": "interval",
    "weekly": "weekly", "monthly": "monthly", "cron": "cron", "once": "once",
}


def _map_automation_entry(e: dict) -> dict:
    """One ``franklinwh-automations`` entry → our portable schedule schema."""
    spec = e.get("trigger_spec") or {}
    tt = _AUTOMATION_TRIGGER.get((e.get("trigger_kind") or "daily").lower(), "daily")
    when = e.get("when_spec") or {}
    ec = e.get("entry_conditions") or {}
    xc = e.get("exit_conditions") or None
    dur_s = e.get("duration_s")
    tgt = e.get("target_id")
    out = {
        "name": e.get("name") or "(imported)",
        "enabled": bool(e.get("enabled")),
        "action": _map_automation_action(e.get("action"), e.get("params")),
        "trigger_type": tt,
        "fire_at": spec.get("time_of_day") or "18:00",
        "interval_min": spec.get("minutes") or spec.get("interval_min") or 30,
        "cron": spec.get("cron") or "0 3 * * *",
        "anchor": spec.get("anchor") or "",
        "duration_min": int(round(dur_s / 60)) if isinstance(dur_s, (int, float)) else 90,
        "match": str(ec.get("match", "all")).lower(),
        "conditions": _map_conditions(ec.get("conditions")),
        "exit_match": str((xc or {}).get("match", "all")).lower(),
        "exit_conditions": _map_conditions((xc or {}).get("conditions")) if xc else [],
        "days": when.get("days") or [],
        "windows": when.get("windows") or [],
        "entry_hold_s": e.get("entry_hold_s") or 0,
        "priority": e.get("priority") or 0,
        "conflict": e.get("conflict") or "override",
        # gateway: a foreign "default"/gateway target → our default gateway ("")
        "gateway_id": "" if (e.get("target_type") != "gateway" or tgt in (None, "default")) else tgt,
        # HA actions share the {instance_id, entity_id, service, data, when} shape already.
        "ha_actions": [h for h in (e.get("ha_actions") or []) if isinstance(h, dict)],
    }
    return out


def import_entries(bundle_type: str | None, entries: list) -> list:
    """Normalise a bundle's entries to OUR schema. Our own type (or none) passes through;
    the Modbus/other ``franklinwh-automations`` type is mapped field-by-field. Returns the
    entries ready for :func:`validate_import` / create."""
    if bundle_type == IMPORT_TYPE_AUTOMATIONS:
        return [_map_automation_entry(e) for e in (entries or []) if isinstance(e, dict)]
    return list(entries or [])


# ── reverse: OUR schema → the Modbus bridge's franklinwh-automations bundle ────
_FORCE_ACTION_REV = {"charge": "force_charge", "discharge": "force_discharge",
                     "standby": "force_standby"}


def _to_automation_action(action) -> tuple:
    """Our action object → (action string, params) for franklinwh-automations."""
    a = action or {}
    kind = a.get("kind")
    if kind == "force":
        act = _FORCE_ACTION_REV.get((a.get("direction") or "").lower(), "none")
        params: dict = {}
        if (a.get("unit") or "pct") == "pct":
            params["power_pct"] = a.get("power")
        else:
            params["power_w"] = a.get("power")
        if a.get("target_soc"):
            params["target_soc"] = a.get("target_soc")
        return act, params
    if kind == "set_mode":
        return "set_mode", {"mode": a.get("mode")}
    if kind == "reserve_soc":
        return ("reserve_self" if a.get("mode") == "self" else "reserve_tou"), {"pct": a.get("soc")}
    if not kind:
        return "none", {}
    # local-only actions (smart_circuit / offgrid / notify) have no Modbus equivalent —
    # keep the kind + its params so nothing is silently dropped (the far side flags it).
    return kind, {k: v for k, v in a.items() if k != "kind"}


def _to_automation_conditions(nodes) -> list:
    out = []
    for n in nodes or []:
        if not isinstance(n, dict):
            continue
        if "conditions" in n or "match" in n:
            out.append({"match": str(n.get("match", "all")).upper(),
                        "conditions": _to_automation_conditions(n.get("conditions"))})
        else:
            leaf = {"sensor": n.get("sensor"), "op": n.get("op"), "value": n.get("value")}
            if "value2" in n:
                leaf["value2"] = n.get("value2")
            out.append(leaf)
    return out


def to_automations(entry: dict) -> dict:
    """One of OUR schedules → a ``franklinwh-automations`` entry (inverse of the import)."""
    act, params = _to_automation_action(entry.get("action"))
    tt = entry.get("trigger_type") or "daily"
    spec: dict = {}
    if tt in ("daily", "window", "weekly", "monthly", "once"):
        spec["time_of_day"] = entry.get("fire_at") or "18:00"
    if tt == "interval":
        spec["minutes"] = entry.get("interval_min") or 30
    if tt == "cron":
        spec["cron"] = entry.get("cron") or "0 3 * * *"
    xconds = entry.get("exit_conditions") or []
    dur = entry.get("duration_min")
    gid = entry.get("gateway_id")
    return {
        "name": entry.get("name") or "",
        "action": act, "params": params,
        "target_type": "gateway", "target_id": gid or "default",
        "enabled": bool(entry.get("enabled")),
        "trigger_kind": tt, "trigger_spec": spec,
        "when_spec": {"days": entry.get("days") or [], "windows": entry.get("windows") or []},
        "entry_conditions": {"match": str(entry.get("match", "all")).upper(),
                             "conditions": _to_automation_conditions(entry.get("conditions"))},
        "exit_conditions": ({"match": str(entry.get("exit_match", "all")).upper(),
                             "conditions": _to_automation_conditions(xconds)} if xconds else None),
        "duration_s": int(dur * 60) if isinstance(dur, (int, float)) else None,
        "entry_hold_s": entry.get("entry_hold_s") or 0,
        "priority": entry.get("priority") or 0,
        "conflict": entry.get("conflict") or "defer",
        "ha_actions": entry.get("ha_actions") or [],
    }


def validate_import(entry: dict, *, gateway_ids: set, device_ids: set) -> dict:
    """Check one imported entry. Returns ``{name, ok, errors, warnings}`` — never
    raises, so a whole bundle is reported at once rather than failing on the first
    bad row."""
    errors: list[str] = []
    warnings: list[str] = []
    name = entry.get("name") or "(unnamed)"
    if not entry.get("name"):
        errors.append("missing name")

    at = entry.get("fire_at", "")
    if not re.match(r"^([01]?\d|2[0-3]):[0-5]\d$", str(at)):
        errors.append(f"fire_at '{at}' is not HH:MM")

    for dk in ("start_date", "end_date"):
        dv = entry.get(dk)
        if dv:
            try:
                dt.date.fromisoformat(str(dv))
            except ValueError:
                errors.append(f"{dk} '{dv}' is not YYYY-MM-DD")

    action = entry.get("action") or {}
    kind = action.get("kind")
    if kind and kind not in ACTIONS:
        errors.append(f"unknown action '{kind}'"
                      + (f" — {UNAVAILABLE[kind]}" if kind in UNAVAILABLE else ""))

    gid = entry.get("gateway_id")
    if gid and gid not in gateway_ids:
        warnings.append(f"gateway '{gid}' not found — will use the default gateway")

    for ha in entry.get("ha_actions") or []:
        did = ha.get("device_id")
        if did and did not in device_ids:
            warnings.append(f"notify device '{did}' not found — set it after import")

    return {"name": name, "ok": not errors, "errors": errors, "warnings": warnings}


def timeline_segments(entries: list[dict], now: dt.datetime) -> dict[str, Any]:
    """A day's windows per ENABLED entry, as minutes-from-midnight, for the
    24-hour bar. Handles windows that wrap past midnight (end <= start)."""
    segments = []
    for e in entries:
        if not e.get("enabled"):
            continue
        tt = e.get("trigger_type") or "daily"
        if tt in ("interval", "cron", "always"):    # no fixed daily window to draw
            continue
        if not _calendar_ok(e, now.date())[0]:      # not scheduled to run today
            continue
        for (start, dur) in _windows_for(e):
            end = start + dur if dur > 0 else start
            segments.append({
                "schedule_id": e["id"], "name": e["name"],
                "action": (e.get("action") or {}).get("kind") or "notify-only",
                "gateway_id": e.get("gateway_id") or "",
                "start_min": start, "end_min": end % (24 * 60) if dur else start,
                "wraps_midnight": dur > 0 and (start + dur) > 24 * 60,
            })
    return {"now_min": now.hour * 60 + now.minute, "segments": segments}


def snapshot_from_state(state: dict, power: dict | None = None) -> dict[str, Any]:
    """Flatten the poller's last state into the ``sensor.id`` namespace that
    conditions and message variables both use — one vocabulary, not two."""
    st = dict(state or {})
    snap: dict[str, Any] = {
        "battery.soc_pct": st.get("soc"),
        "battery.power_w": st.get("battery_w"),
        "grid.power_w": st.get("grid_w"),
        "solar.power_w": st.get("solar_w"),
        "load.power_w": st.get("load_w"),
        "generator.power_w": st.get("generator_w"),
        "mode.name": st.get("mode"),
        "bridge.latency_ms": st.get("latency_ms"),
    }
    # grid.connected is derived, so say so rather than implying a device field.
    grid = st.get("grid_w")
    snap["grid.connected"] = None if grid is None else int(grid != 0)
    # state IS the summary power block (poller sets last_state = summary['power']), so the daily
    # solar counter is here — available in the scheduler ENGINE tick too (where power is None).
    snap["solar.today_kwh"] = st.get("kwh_sun")   # actual PV generated today
    if power:
        snap["run_status"] = power.get("run_status")
    return snap


def ha_sensor_id(instance_id: str, entity_id: str) -> str:
    """The scheduler id for an exposed HA entity: ``ha:<instance>:<entity>``.

    Same namespace the Modbus Bridge uses, so a condition can gate on a Home
    Assistant value exactly as it does on a local one.
    """
    return f"ha:{instance_id}:{entity_id}"


def _coerce(state: Any) -> Any:
    """HA states are strings. Compare numerically when they look numeric, and map
    on/off to 1/0 so a binary_sensor works in a `== 1` condition."""
    if isinstance(state, str):
        low = state.strip().lower()
        if low in ("on", "true", "open", "home"):
            return 1
        if low in ("off", "false", "closed", "away", "unavailable", "unknown"):
            return 0
        try:
            return float(state)
        except ValueError:
            return state
    return state


def ha_snapshot(store) -> dict[str, Any]:
    """Live values for the EXPOSED HA entities, keyed ha:<instance>:<entity>.

    Only exposed entities are read — a scheduler that pulled all 3,949 every tick
    would hammer Home Assistant. Missing/unreachable ones are simply absent, and an
    absent sensor already counts as False in evaluate().
    """
    exposed = store.ha_exposed_ids()
    if not exposed:
        return {}
    want = {e.split(":", 1)[0]: set() for e in exposed}
    for e in exposed:
        inst, eid = e.split(":", 1)
        want.setdefault(inst, set()).add(eid)
    out: dict[str, Any] = {}
    for inst in store.ha_instances():
        if not inst.get("enabled") or inst["id"] not in want:
            continue
        try:
            for st in ha_instances.states(inst["base_url"], inst.get("token")):
                eid = st.get("entity_id", "")
                if eid in want[inst["id"]]:
                    out[ha_sensor_id(inst["id"], eid)] = _coerce(st.get("state"))
        except Exception:                                       # noqa: BLE001
            continue
    return out


def ha_sensor_options(store) -> list[dict[str, Any]]:
    """Exposed HA entities as scheduler sensor options, grouped by instance —
    the picker the Modbus Bridge shows under 'HA Live: …'."""
    exposed = store.ha_exposed_ids()
    if not exposed:
        return []
    names = {i["id"]: i["name"] for i in store.ha_instances()}
    out = []
    for e in sorted(exposed):
        inst, eid = e.split(":", 1)
        out.append({"id": ha_sensor_id(inst, eid),
                    "label": f"{names.get(inst, inst)}: {eid}",
                    "group": names.get(inst, inst)})
    return out


SENSORS = [
    ("battery.soc_pct", "Battery SoC (%)"),
    ("battery.power_w", "Battery power (W)"),
    ("grid.power_w", "Grid power (W)"),
    ("grid.connected", "Grid connected"),
    ("solar.power_w", "Solar power (W)"),
    ("load.power_w", "Home load (W)"),
    ("generator.power_w", "Generator power (W)"),
    ("mode.name", "Operating mode"),
    ("bridge.latency_ms", "Round-trip latency (ms)"),
]

#: Weather + solar-forecast sensors (Open-Meteo), a separate group in the picker.
SOLAR_SENSORS = [
    ("weather.temp_c", "Weather: temperature (°C)"),
    ("weather.condition", "Weather: condition"),
    ("solar_forecast.today_kwh", "Solar forecast: today (kWh)"),
    ("solar_forecast.today_peak_kw", "Solar forecast: today peak (kW)"),
    ("solar_forecast.remaining_kwh", "Solar forecast: remaining today (kWh)"),
    ("solar_forecast.tomorrow_kwh", "Solar forecast: tomorrow (kWh)"),
    ("solar.today_kwh", "Solar generated today, actual (kWh)"),
]

#: User-defined automation constants (SoC parameters) — a separate "Automation
#: Constants" group in the picker. Values live in the metrics store (see constants.py).
CONST_SENSORS = [
    ("const.min_discharge_soc", "Const: min discharge SoC (%)"),
    ("const.max_charge_soc", "Const: max charge SoC (%)"),
    ("const.demand_charge_min_soc", "Const: demand-charge min SoC (%)"),
    ("const.default_operating_mode", "Const: default operating mode"),
]


def const_snapshot(store) -> dict[str, Any]:
    """const.* values for the gate snapshot (empty/defaults when unset)."""
    try:
        from . import constants
        return constants.snapshot(store)
    except Exception:                                           # noqa: BLE001
        return {}


def ratings_snapshot(host: str | None) -> dict[str, Any]:
    """Battery max charge/discharge (W) from Modbus SunSpec 702, cached ~1 h. Empty
    when Modbus is disabled/unreachable — the at-max-rate ETA then falls back to the
    battery_max_power_kw constant. Only Modbus can read the model-correct rating."""
    if not host:
        return {}
    try:
        from . import battery_control
        chg, dis = battery_control.cached_ratings(host)
        out: dict[str, Any] = {}
        if chg is not None:
            out["ratings.max_charge_w"] = chg
        if dis is not None:
            out["ratings.max_discharge_w"] = dis
        return out
    except Exception:                                           # noqa: BLE001
        return {}


#: Derived battery sensors — computed from live points + user constants (capacity +
#: SoC targets), so a schedule can gate on stored energy / headroom / ETA without the
#: user doing the arithmetic. All fail-closed (None) when an input is missing. Ported
#: from the Modbus bridge. A separate "Derived Battery" group in the picker.
DERIVED_SENSORS = [
    ("battery.status", "Battery state (charging / discharging / standby)"),
    ("battery.capacity_kwh", "Battery capacity (kWh)"),
    ("battery.stored_kwh", "Battery stored energy (kWh)"),
    ("battery.remaining_kwh", "Battery headroom to full (kWh)"),
    ("battery.time_to_charge_now_min", "ETA to max-charge SoC at current rate (min)"),
    ("battery.time_to_discharge_now_min", "ETA to min-discharge SoC at current rate (min)"),
    ("battery.time_to_charge_min", "ETA to max-charge SoC at max rate (min)"),
    ("battery.time_to_discharge_min", "ETA to min-discharge SoC at max rate (min)"),
    ("solar_forecast.day_pct", "Solar tracker: % of today's forecast reached"),
    ("solar_forecast.vs_expected_pct", "Solar tracker: % vs forecast-to-now (>100 ahead, <100 behind)"),
]


def _dnum(snap: dict, k: str) -> float | None:
    v = snap.get(k)
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _eta_now_min(cap, stored, target_soc, signed_w, *, charging: bool) -> float | None:
    """Minutes to reach target_soc at the CURRENT battery power. signed_w < 0 is
    charging, > 0 is discharging (local convention). None when not moving toward the
    target (idle / wrong direction), 0.0 when already at/past it."""
    if cap is None or stored is None or target_soc is None or signed_w is None:
        return None
    target_kwh = cap * target_soc / 100.0
    if charging:
        rate_kw = -signed_w / 1000.0
        delta = target_kwh - stored
    else:
        rate_kw = signed_w / 1000.0
        delta = stored - target_kwh
    if rate_kw <= 0:
        return None
    if delta <= 0:
        return 0.0
    return round(delta / rate_kw * 60.0, 1)


def _eta_min(cap, stored, target_soc, rate_w, *, charging: bool) -> float | None:
    """Best-case minutes to reach target_soc at a constant rate_w (the max rate)."""
    if cap is None or stored is None or target_soc is None or not rate_w:
        return None
    target_kwh = cap * target_soc / 100.0
    delta = (target_kwh - stored) if charging else (stored - target_kwh)
    if delta <= 0:
        return 0.0
    return round(delta / (rate_w / 1000.0) * 60.0, 1)


def derived_snapshot(snap: dict) -> dict[str, Any]:
    """battery.* derived fields from an already-built snapshot (needs battery.soc_pct,
    battery.power_w, and the const.* capacity + SoC targets already merged in)."""
    soc = _dnum(snap, "battery.soc_pct")
    pw = _dnum(snap, "battery.power_w")                 # signed: <0 charging, >0 discharging
    cap = _dnum(snap, "const.battery_capacity_kwh")
    cap = cap if (cap and cap > 0) else None
    stored = round(cap * soc / 100.0, 2) if (cap is not None and soc is not None) else None
    out: dict[str, Any] = {
        "battery.capacity_kwh": cap,
        "battery.stored_kwh": stored,
        "battery.remaining_kwh": (round(cap - stored, 2) if (cap is not None and stored is not None) else None),
        "battery.time_to_charge_now_min": _eta_now_min(
            cap, stored, _dnum(snap, "const.max_charge_soc"), pw, charging=True),
        "battery.time_to_discharge_now_min": _eta_now_min(
            cap, stored, _dnum(snap, "const.min_discharge_soc"), pw, charging=False),
    }
    # "at max rate" ETAs — Modbus 702 rate if available, else the battery_max_power_kw
    # constant (kW → W). Direction-correct (separate charge/discharge when Modbus gives both).
    fb = _dnum(snap, "const.battery_max_power_kw")
    fb_w = fb * 1000.0 if (fb and fb > 0) else None
    max_ch = _dnum(snap, "ratings.max_charge_w") or fb_w
    max_dis = _dnum(snap, "ratings.max_discharge_w") or fb_w
    out["battery.time_to_charge_min"] = _eta_min(
        cap, stored, _dnum(snap, "const.max_charge_soc"), max_ch, charging=True)
    out["battery.time_to_discharge_min"] = _eta_min(
        cap, stored, _dnum(snap, "const.min_discharge_soc"), max_dis, charging=False)
    if pw is not None:
        out["battery.status"] = "charging" if pw < 0 else "discharging" if pw > 0 else "standby"
    # Solar tracker: actual PV today vs the Open-Meteo forecast (both already in the snapshot).
    actual = _dnum(snap, "solar.today_kwh")
    fc_today = _dnum(snap, "solar_forecast.today_kwh")
    fc_remaining = _dnum(snap, "solar_forecast.remaining_kwh")
    if actual is not None and fc_today and fc_today > 0:
        out["solar_forecast.day_pct"] = round(actual / fc_today * 100, 1)
    expected = (fc_today - fc_remaining) if (fc_today is not None and fc_remaining is not None) else None
    if actual is not None and expected and expected > 0:
        out["solar_forecast.vs_expected_pct"] = round(actual / expected * 100, 1)
    return out


def nem_snapshot(settings) -> dict[str, Any]:
    """Wholesale spot sensor from the AEMO NEM built-in — {tariff.spot_price} in c/kWh when a
    nem_region is configured. Cached in aemo_nem (~4min); empty otherwise or on fetch failure."""
    region = getattr(settings, "nem_region", "") or ""
    if not region:
        return {}
    try:
        from . import aemo_nem
        sp = aemo_nem.spot_price(region)
        return {"tariff.spot_price": sp.get("price_c_kwh")} if sp else {}
    except Exception:                                          # noqa: BLE001
        return {}


def solar_snapshot(settings) -> dict[str, Any]:
    """Weather/solar-forecast values for the gate snapshot. Empty when the location
    is not configured or the fetch fails; cached ~15min, so cheap to call per tick."""
    try:
        lat = getattr(settings, "pv_latitude", None)
        lon = getattr(settings, "pv_longitude", None)
        if lat is None or lon is None:
            return {}
        from . import solar_forecast
        fc = solar_forecast.forecast(lat, lon, kwp=settings.pv_kwp,
                                     tilt=settings.pv_tilt, azimuth=settings.pv_azimuth)
        return solar_forecast.sensors(fc)
    except Exception:                                           # noqa: BLE001
        return {}


#: Tariff + utility sensors — the meter's rate plan (rate_model) + its utility's
#: export/charge permissions. A separate "Tariff & Utility" group in the picker.
def _ha_price_to_c_kwh(state_obj) -> float | None:
    """Coerce an HA price entity's state to c/kWh. Auto-detects dollars: a
    ``$/kWh`` unit (e.g. 0.28) is scaled x100 to cents; a ``c/kWh`` / ``¢/kWh``
    (or unitless, Amber's native) value is taken as-is. Feed-in may be negative."""
    try:
        v = float(state_obj.get("state"))
    except (TypeError, ValueError):
        return None
    unit = str((state_obj.get("attributes") or {}).get("unit_of_measurement") or "")
    u = unit.lower()
    if "$" in unit or u.startswith("aud") or "dollar" in u:
        return round(v * 100.0, 4)          # $/kWh -> c/kWh
    return round(v, 4)                       # already c/kWh (or Amber-native cents)


def _ha_prices_c(store, ids) -> dict[str, float]:
    """Read the given ``ha:<inst>:<eid>`` price entities -> {id: c/kWh}. Bounded to the
    involved instances; unit-detected; never raises. Shared by the global HA price provider
    and the per-tariff dynamic provider."""
    want: dict[str, dict[str, str]] = {}
    for sid in ids:
        sid = (sid or "").strip()
        if sid.startswith("ha:") and sid.count(":") >= 2:
            _, inst, eid = sid.split(":", 2)
            want.setdefault(inst, {})[eid] = sid
    if not want:
        return {}
    resolved: dict[str, float] = {}
    try:
        insts = {i["id"]: i for i in store.ha_instances()}
    except Exception:                                           # noqa: BLE001
        return {}
    for inst_id, eids in want.items():
        inst = insts.get(inst_id)
        if not inst or not inst.get("enabled"):
            continue
        try:
            for st in ha_instances.states(inst["base_url"], inst.get("token")):
                eid = st.get("entity_id", "")
                if eid in eids:
                    c = _ha_price_to_c_kwh(st)
                    if c is not None:
                        resolved[eids[eid]] = c
        except Exception:                                       # noqa: BLE001
            continue
    return resolved


def tariff_dynamic_provider(store, gateway_id) -> dict | None:
    """The ACTIVE tariff's dynamic-pricing provider config, or None when the tariff is not
    ``kind:dynamic``. Shape: {source:'nem', region:'NSW1'} or {source:'ha', buy_entity, feedin_entity}."""
    try:
        from . import billing
        cfg = billing._billing_cfg(store, gateway_id)
        pr = (cfg or {}).get("pricing") or {}
        if pr.get("kind") == "dynamic":
            return pr.get("dynamic") or {}
    except Exception:                                           # noqa: BLE001
        pass
    return None


def resolve_dynamic_price(dyn: dict, store) -> tuple:
    """(buy_c_kwh, sell_c_kwh) for a dynamic provider config, or (None, None). NEM uses the
    tariff's own region; HA uses the tariff's own buy/feed-in entities (sell falls back to buy)."""
    src = (dyn or {}).get("source")
    if src == "nem":
        from . import aemo_nem
        sp = aemo_nem.spot_price((dyn.get("region") or "").upper())
        if sp:
            return sp.get("price_c_kwh"), sp.get("price_c_kwh")
    elif src == "ha":
        buy_id = (dyn.get("buy_entity") or "").strip()
        feed_id = (dyn.get("feedin_entity") or "").strip()
        got = _ha_prices_c(store, [buy_id, feed_id])
        buy = got.get(buy_id)
        sell = got.get(feed_id)
        if buy is not None:
            return buy, (sell if sell is not None else buy)
    return None, None


def apply_dynamic_pricing(snapshot: dict, settings, store, gateway_id) -> dict | None:
    """FEAT-BILLING-WHOLESALE (per-tariff): when the ACTIVE tariff is ``kind:dynamic``, resolve
    the live price from THAT tariff's own provider (AusNEM region or HA entity), OVERRIDE the
    tariff.spot_price/feed_in_price + buy_rate/sell_rate sensors (option B: an active dynamic
    tariff wins over the global sensor source), and return the live ``{buy, sell}`` $/kWh for
    billing. Returns None (static tariff) otherwise — the global nem/ha sensors then stand."""
    dyn = tariff_dynamic_provider(store, gateway_id)
    if not dyn:
        return None
    buy_c, sell_c = resolve_dynamic_price(dyn, store)
    if buy_c is None:
        return None
    snapshot["tariff.spot_price"] = round(buy_c, 4)
    if sell_c is not None:
        snapshot["tariff.feed_in_price"] = round(sell_c, 4)
    buy = buy_c / 100.0
    sell = (sell_c / 100.0) if sell_c is not None else buy
    snapshot["tariff.buy_rate"] = round(buy, 5)
    snapshot["tariff.sell_rate"] = round(sell, 5)
    return {"buy": buy, "sell": sell}


def ha_price_snapshot(settings, store) -> dict[str, Any]:
    """Dynamic-tariff price sensors sourced from a chosen HA entity — the second
    wholesale provider (the first is the AusNEM built-in, see :func:`nem_snapshot`).

    ``tariff_price_entity`` -> ``tariff.spot_price`` (buy, c/kWh);
    ``tariff_feedin_entity`` -> ``tariff.feed_in_price`` (sell, c/kWh). Entities are
    the scheduler ids ``ha:<instance>:<entity_id>``. Reads state+unit directly (so it
    can unit-detect), bounded to the involved instances. Never raises; an absent or
    unreachable entity is simply absent, and applied AFTER nem_snapshot so a
    configured HA entity wins over NEM for the same sensor."""
    price_id = (getattr(settings, "tariff_price_entity", "") or "").strip()
    feed_id = (getattr(settings, "tariff_feedin_entity", "") or "").strip()
    if not price_id and not feed_id:
        return {}
    resolved = _ha_prices_c(store, [price_id, feed_id])
    out: dict[str, Any] = {}
    if price_id in resolved:
        out["tariff.spot_price"] = resolved[price_id]
    if feed_id in resolved:
        out["tariff.feed_in_price"] = resolved[feed_id]
    return out


TARIFF_SENSORS = [
    ("tariff.spot_price", "Wholesale spot price (AEMO NEM or HA entity, c/kWh)"),
    ("tariff.feed_in_price", "Dynamic feed-in price (HA entity, c/kWh)"),
    ("tariff.buy_rate", "Tariff: import rate ($/kWh)"),
    ("tariff.sell_rate", "Tariff: feed-in rate ($/kWh)"),
    ("tariff.season", "Tariff: season"),
    ("tariff.time_period", "Tariff: time period"),
    ("tariff.tier", "Tariff: tier"),
    ("tariff.import_billable", "Tariff: import billable"),
    ("service.export_allowed", "Utility: export allowed"),
    ("service.solar_export_allowed", "Utility: solar export allowed"),
    ("service.battery_export_allowed", "Utility: battery export allowed"),
    ("service.charging_allowed", "Utility: charging allowed"),
    ("service.discharging_allowed", "Utility: discharging allowed"),
    ("service.export_limit_kw", "Utility: export limit (kW)"),
    ("service.plan_type", "Utility: plan type"),
]


#: Billing/tariff WINDOW sensors (Phase 1 of the billing engine) — is `now` inside the
#: meter's tariff demand / bonus / export-charge / grid-import window. Informational
#: (express-don't-enforce): None when a window is not configured. Group with Tariff.
BILLING_WINDOW_SENSORS = [
    ("tariff.demand_window_active", "Tariff: in peak-demand window"),
    ("tariff.bonus_window_active", "Tariff: in battery-export-bonus window"),
    ("tariff.export_charge_window_active", "Tariff: in export-charge window"),
    ("tariff.import_window_active", "Tariff: in a declared grid-import window"),
]


#: Demand-charge sensors (billing Phase 2) — peak/interval grid-import demand + the
#: demand charge to date, from the meter's tariff demand_window + rate. "Demand / Tariff".
DEMAND_SENSORS = [
    ("demand.peak_kw", "Demand: peak this period (kW)"),
    ("demand.interval_kw", "Demand: current interval (kW, running)"),
    ("demand.period_charge", "Demand: charge this period ($)"),
]


#: Energy cost sensors (billing Phase 3) — period import/export + $ integrated against
#: the rate in force. Group "Energy".
ENERGY_SENSORS = [
    ("energy.period_import_kwh", "Energy: grid import this period (kWh)"),
    ("energy.import_cost", "Energy: grid import cost this period ($)"),
    ("energy.export_credit", "Energy: grid export credit this period ($)"),
    ("energy.unpriced_import_kwh", "Energy: import the plan priced no rate for (kWh)"),
    ("energy.unpriced_export_kwh", "Energy: export the plan priced no rate for (kWh)"),
]

#: Battery-export bonus (billing Phase 3). Group "Demand / Tariff".
BONUS_SENSORS = [
    ("bonus.export_kwh", "Bonus: export in the bonus window this period (kWh)"),
    ("bonus.period_credit", "Bonus: battery-export credit this period ($)"),
]

#: Two-way / solar-sponge export CHARGE (billing Phase 3). Group "Tariff & Utility".
EXPORT_CHARGE_SENSORS = [
    ("tariff.export_charge_kwh", "Tariff: export-charge export this period (kWh)"),
    ("tariff.export_charge_free_remaining", "Tariff: free export allowance remaining (kWh)"),
    ("tariff.export_charge_net_kwh", "Tariff: chargeable export above free (kWh)"),
    ("tariff.export_charge_cost", "Tariff: export charge this period ($)"),
]

#: Standing/fixed charges (billing Phase 4) — deterministic time accrual. Group "Fixed Charges".
FIXED_SENSORS = [
    ("fixed.daily_charge", "Fixed: charges per day ($)"),
    ("fixed.accrued_period", "Fixed: accrued this period ($)"),
    ("fixed.period_total", "Fixed: projected this period ($)"),
    ("fixed.remaining", "Fixed: left to cover this period ($)"),
    ("fixed.days_remaining", "Fixed: days left in billing period"),
]

#: System Setup / install profile (FEAT-SYSTEM-SETUP) — derived from the aGate + user
#: override. Group "System Setup".
SYSTEM_SENSORS = [
    ("system.solar_type", "System: solar type (none/ac/dc/remote)"),
    ("system.solar_kwp", "System: solar size (kWp)"),
    ("system.generator_input", "System: generator input"),
    ("system.grid_forming", "System: grid-forming"),
    ("system.whole_home_backup", "System: whole-home backup"),
    ("system.load_shedding", "System: load shedding"),
    ("system.non_backup_loads", "System: non-backup loads panel"),
    ("system.battery_label", "System: battery label"),
]


def _in_window(win: Any, now: dt.datetime) -> bool:
    """Is `now` inside a tariff window {months, days, start, end}? Empty months/days
    = all. Same-day range or overnight wrap (start > end). Ported from the Modbus
    bridge's billing window matcher; reuses rate_model._hhmm (minutes-since-midnight)."""
    if not isinstance(win, dict):
        return False
    months = {int(m) for m in (win.get("months") or []) if 1 <= int(m) <= 12}
    if months and now.month not in months:
        return False
    days = {int(d) for d in (win.get("days") or []) if 0 <= int(d) <= 6}
    if days and now.weekday() not in days:
        return False
    from . import rate_model
    hs, he = rate_model._hhmm(win.get("start")), rate_model._hhmm(win.get("end"))
    if hs is None or he is None:
        return True                                    # no time bound → whole day
    cur = now.hour * 60 + now.minute
    if hs <= he:
        return hs <= cur < he
    return cur >= hs or cur < he                        # overnight wrap


def billing_snapshot(store, gateway_id=None, now: dt.datetime | None = None) -> dict[str, Any]:
    """tariff.*_window_active for the gateway's meter's tariff. Empty when no tariff;
    a given window is None when that tariff doesn't define it (so a gate on it fails
    closed — the safe default). Windows: demand_window / bonus_window / charge_window
    (JSON columns) + pricing.import_windows[]."""
    now = now or dt.datetime.now()
    meter = _meter_for_gateway(store, gateway_id)
    if not meter:
        return {}
    try:
        tar = store.tariff(meter.get("tariff_id")) if meter.get("tariff_id") else None
    except Exception:                                          # noqa: BLE001
        tar = None
    if not tar:
        return {}
    dw = tar.get("demand_window") if isinstance(tar.get("demand_window"), dict) else None
    bw = tar.get("bonus_window") if isinstance(tar.get("bonus_window"), dict) else None
    cw = tar.get("charge_window") if isinstance(tar.get("charge_window"), dict) else None
    pricing = tar.get("pricing") if isinstance(tar.get("pricing"), dict) else {}
    imports = [w for w in (pricing.get("import_windows") or []) if isinstance(w, dict)]
    return {
        "tariff.demand_window_active": (int(_in_window(dw, now)) if dw else None),
        "tariff.bonus_window_active": (int(_in_window(bw, now)) if bw else None),
        "tariff.export_charge_window_active": (int(_in_window(cw, now)) if cw else None),
        "tariff.import_window_active": (int(any(_in_window(w, now) for w in imports)) if imports else None),
    }


def _meter_for_gateway(store, gateway_id):
    """The meter a gateway connects to, else the (default site's) default meter."""
    try:
        if store is None:
            return None
        gw = store.gateway(gateway_id) if gateway_id else None
        mid = (gw or {}).get("meter_id")
        if mid:
            return store.meter(mid)
        meters = store.meters()
        return next((m for m in meters if m.get("is_default")), (meters or [None])[0])
    except Exception:                                           # noqa: BLE001
        return None


def tariff_snapshot(store, gateway_id=None, now: dt.datetime | None = None) -> dict[str, Any]:
    """tariff.* + service.* for the gateway's meter's tariff + utility. Empty when
    unconfigured — a sensor then reads None and a gate fails closed (never fires),
    which is the safe default. Tiered pricing uses the first tier here (the billing
    engine will later supply period-to-date use for exact tiering)."""
    now = now or dt.datetime.now()
    meter = _meter_for_gateway(store, gateway_id)
    if not meter:
        return {}
    out: dict[str, Any] = {}
    try:
        util = store.utility(meter.get("utility_id")) if meter.get("utility_id") else None
        if util:
            out.update({
                "service.export_allowed": int(util.get("export_allowed", 1)),
                "service.solar_export_allowed": int(util.get("solar_export_allowed", 1)),
                "service.battery_export_allowed": int(util.get("battery_export_allowed", 1)),
                "service.charging_allowed": int(util.get("charging_allowed", 1)),
                "service.discharging_allowed": int(util.get("discharging_allowed", 1)),
                "service.export_limit_kw": util.get("export_limit_kw"),
                "service.plan_type": util.get("plan_type"),
            })
        tar = store.tariff(meter.get("tariff_id")) if meter.get("tariff_id") else None
        if tar and isinstance(tar.get("pricing"), dict):
            from . import rate_model
            pr = tar["pricing"]
            r = rate_model.resolve(pr.get("seasons"), now, default_rate=pr.get("default_rate"))
            out.update({
                "tariff.buy_rate": r.get("buy"),
                "tariff.sell_rate": r.get("sell"),
                "tariff.season": r.get("season"),
                "tariff.time_period": r.get("time_period"),
                "tariff.tier": r.get("tier"),
                "tariff.import_billable": (int(r["billable"]) if r.get("billable") is not None else None),
            })
    except Exception:                                           # noqa: BLE001
        pass
    return out


#: Force-dispatch direction -> Battery Command slug (direct-Modbus WSet).
_FORCE_SLUG: dict[str, str] = {
    "charge": "Force Charge", "discharge": "Force Discharge", "standby": "Force Standby",
}


def _force_dispatch(action: dict, *, host: str | None, window_min: int,
                    gateway_id: str | None, store, dry_run: bool = False,
                    release: bool = False, schedule_id: str | None = None,
                    schedule_name: str | None = None, window_end_ts: float | None = None) -> str:
    """Force charge/discharge/standby over the direct-Modbus path (battery_control) —
    the same engine the dashboard widget uses, independent of the modbus-bridge.

    The dispatch runs for the schedule WINDOW (``window_min``): the bridge's own
    watchdog auto-releases at window end and also enforces ``target_soc`` (charge
    stops at SoC>=target, discharge at SoC<=target), reading live SoC from this
    gateway's last poll. ``release=True`` ends the dispatch, fired on the window's
    exit edge as a safety net so a force never outlives its window. Never raises.
    """
    from . import battery_control
    from . import state as _state
    if not host:
        return "force skipped: no gateway host to reach over Modbus"
    if release:
        out = battery_control.execute("Release", host=host, dry_run=dry_run)
        return f"force release: {out.get('result', '')}"
    direction = (action.get("direction") or "").lower()
    slug = _FORCE_SLUG.get(direction)
    if not slug:
        return f"force skipped: unknown direction '{direction}'"
    unit = (action.get("unit") or "pct").lower()
    power = float(action.get("power") or 0)
    if unit == "kw":
        power_w, power_pct, mode = int(power * 1000), 100, "w"
    elif unit == "w":
        power_w, power_pct, mode = int(power), 100, "w"
    else:                          # percent of the rated rate for the direction
        power_w, power_pct, mode = 0, int(power), "pct"

    def _soc():
        try:
            gw = _state.get_gateway(gateway_id) if gateway_id else _state.get_state()
            return (getattr(gw, "last_state", {}) or {}).get("soc")
        except Exception:                                       # noqa: BLE001
            return None

    def _log(status, detail):
        try:
            store.log_schedule_event("_batt", "Battery dispatch (schedule)", status, detail)
            # A clean end (watchdog duration/target, or supersede) closes the persisted
            # row so the boot reconcile does not later see it as interrupted.
            if status == "dispatch-end" and hasattr(store, "end_active_dispatches"):
                store.end_active_dispatches(host=host, status="ended")
        except Exception:                                       # noqa: BLE001
            pass

    tgt = int(action.get("target_soc") or 0)
    out = battery_control.execute(
        slug, host=host, power_w=power_w, power_pct=power_pct, power_mode=mode,
        duration_s=int((window_min or 0) * 60), target_soc=tgt,
        soc_getter=_soc, on_event=_log, dry_run=dry_run)
    # Persist the in-flight dispatch so a bridge restart mid-window can be reconciled.
    if out.get("ok") and not dry_run and hasattr(store, "record_dispatch"):
        try:
            import time as _t
            # Signed magnitude for the reconcile: real watts in 'w' mode, the percent in
            # 'pct' mode (power_mode records which). Sign carries the direction (charge>0,
            # discharge<0) so the watchdog's target-SoC logic works either way.
            mag = int(power_w if mode == "w" else power_pct)
            signed = abs(mag) if direction == "charge" else -abs(mag) if direction == "discharge" else 0
            store.record_dispatch(
                schedule_id=schedule_id, name=schedule_name or "scheduled dispatch",
                gateway_id=gateway_id, host=host, direction=direction, watts=signed,
                power_mode=mode, target_soc=tgt, window_start_ts=_t.time(),
                window_end_ts=window_end_ts)
        except Exception:                                       # noqa: BLE001
            pass
    return f"force {direction}: {out.get('result', '')}"


def run_action(action: dict, *, settings, client, store, snapshot: dict,
               host: str | None = None, window_min: int = 0,
               gateway_id: str | None = None, dry_run: bool = False,
               schedule_id: str | None = None, schedule_name: str | None = None,
               window_end_ts: float | None = None) -> str:
    """Execute one action and return a human-readable outcome.

    Never raises: a failing action must record WHY and let the rest of the
    schedule continue, because a schedule that dies silently on one bad step is
    worse than one that reports a partial run.
    """
    kind = (action or {}).get("kind")
    try:
        if kind == "force":
            return _force_dispatch(action, host=host, window_min=window_min,
                                   gateway_id=gateway_id, store=store, dry_run=dry_run,
                                   schedule_id=schedule_id, schedule_name=schedule_name,
                                   window_end_ts=window_end_ts)

        if kind == "set_mode":
            out = client.set_mode(settings, action["mode"], host=host)
            return f"mode -> {action['mode']}: {'ok' if out.get('ok', True) else out}"

        if kind == "smart_circuit":
            out = client.set_smart_circuit(settings, int(action["circuit"]),
                                           bool(action["on"]), host=host)
            # result:0 means the frame parsed; only the read-back proves it applied.
            return (f"circuit {action['circuit']} -> {'on' if action['on'] else 'off'}: "
                    f"{'confirmed' if out.get('confirmed') else 'NOT confirmed'}")

        if kind == "offgrid":
            out = client.set_offgrid(settings, bool(action["on"]),
                                     int(action.get("soc", 5)), host=host)
            return f"offgrid {action['on']}: {'ok' if out.get('ok') else out}"

        if kind == "notify":
            from . import ha_instances
            dev = store.notify_device(action["device_id"])
            if dev is None:
                return "notify skipped: device no longer exists"
            if not dev.get("enabled"):
                return f"notify skipped: '{dev['alias']}' is switched off"
            inst = store.ha_instance(dev["instance_id"])
            if inst is None:
                return f"notify skipped: '{dev['alias']}' has no HA instance"
            res = ha_instances.send_notification(
                inst["base_url"], inst.get("token"), dev["service"],
                substitute(action.get("title", ""), snapshot),
                substitute(action.get("message", ""), snapshot))
            return (f"notify '{dev['alias']}': "
                    f"{'sent' if res.get('ok') else res.get('error')}")

        if kind == "ha_service":
            from . import ha_instances
            import json as _json
            inst = store.ha_instance(action.get("instance_id"))
            if inst is None:
                return "service skipped: no HA instance selected"
            domain = (action.get("domain") or "").strip()
            service = (action.get("service") or "").strip()
            if not domain or not service:
                return "service skipped: domain and service are required"
            data = action.get("data")
            if isinstance(data, str):
                try:
                    data = _json.loads(data) if data.strip() else {}
                except Exception:                               # noqa: BLE001
                    return "service skipped: data is not valid JSON"
            data = dict(data or {})
            # %sensor.id% substitution in the entity id and any string data values.
            ent = substitute(str(action.get("entity_id") or ""), snapshot).strip()
            if ent:
                data.setdefault("entity_id", ent)
            for k, v in list(data.items()):
                if isinstance(v, str):
                    data[k] = substitute(v, snapshot)
            res = ha_instances.call_service(inst["base_url"], inst.get("token"),
                                            domain, service, data)
            return (f"service {domain}.{service}: "
                    f"{'ok' if res.get('ok') else res.get('error')}")

        if kind == "reserve_soc":
            return ("reserve_soc skipped: no local write path exists "
                    "(see RESEARCH-RESERVE-SOC); needs a cloud provider")

        if kind in UNAVAILABLE:
            return f"{kind} skipped: {UNAVAILABLE[kind]}"
        return f"unknown action '{kind}'"
    except Exception as e:                                       # noqa: BLE001
        return f"{kind} failed: {type(e).__name__}: {e}"


def _is_default_gateway(store, gateway_id: str) -> bool:
    """True if this is the gateway an unbound schedule should run on. Uses the
    first configured gateway as the default when nothing else distinguishes them."""
    try:
        from .state import gateways as _gws
        gw = _gws()
        return bool(gw) and gw[0].id == gateway_id
    except Exception:                                           # noqa: BLE001
        return True     # single-gateway: always the default


#: Dwell (entry_hold_s) timers — when conditions first met, keyed by
#: "gateway:entry". In-memory: a restart restarts the hold, which is the safe
#: direction (never fire earlier than the hold demands).
_dwell_since: dict[str, dt.datetime] = {}

#: Whether each entry's window was inside last tick, keyed "gateway:entry". Used
#: to detect the closing edge so exit-tagged HA actions fire once when a window ends.
_window_inside: dict[str, bool] = {}

#: Last day a "gated" audit line was logged per entry, so a window that is blocked
#: by its conditions is recorded once (not every tick).
_gated_day: dict[str, str] = {}


def gate_reason(entry: dict, snapshot: dict) -> str:
    """A human reason a gate did not pass — the first failing leaf with its live
    value, e.g. ``battery.soc_pct < 20 (live=27.05)``. This is the audit detail."""
    trace: list[dict] = []
    evaluate(entry.get("conditions") or [], snapshot, entry.get("match", "all"), trace)
    fails = [r for r in trace if not r.get("result")]
    if not fails:
        return "entry conditions not met"
    def fmt(r: dict) -> str:
        rhs = r.get("value")
        if r.get("value_kind") == "sensor":
            rhs = r.get("value_sensor")
        elif r.get("op") == "between":
            rhs = f"{r.get('value')}..{r.get('value2')}"
        return f"{r.get('sensor')} {r.get('op')} {rhs} (live={r.get('live_value')})"
    head = "; ".join(fmt(r) for r in fails[:2])
    return head + ("" if len(fails) <= 2 else f"; +{len(fails) - 2} more")



def _guard_ok(guard: dict | None, snapshot: dict) -> bool:
    """An HA action's optional guard — run the action only if it currently holds.
    ``guard`` is either a single leaf ({sensor,op,value}) or a {match,conditions}
    tree; absent/empty means no guard (always run). Missing data fails closed."""
    if not guard:
        return True
    if isinstance(guard, dict) and "conditions" in guard:
        return evaluate(guard.get("conditions") or [], snapshot, guard.get("match", "all"))
    return evaluate([guard], snapshot)


def _fire_ha_phase(entry: dict, phase: str, *, settings, client, store,
                   snapshot: dict, host: str | None) -> list[str]:
    """Run the entry's HA actions tagged for this edge (``fire`` on entry / ``exit``
    on window close; ``both`` runs on each), each gated by its own guard."""
    out: list[str] = []
    for ha in entry.get("ha_actions") or []:
        if (ha.get("when") or "fire") not in (phase, "both"):
            continue
        if not _guard_ok(ha.get("guard"), snapshot):
            continue
        akind = "ha_service" if (ha.get("ha_kind") == "service") else "notify"
        out.append(run_action({**ha, "kind": akind}, settings=settings,
                              client=client, store=store, snapshot=snapshot, host=host))
    return out


def tick(*, settings, client, store, state: dict, host: str | None = None,
         gateway_id: str | None = None, now: dt.datetime | None = None,
         modbus_host: str | None = None) -> list[dict]:
    """Evaluate every schedule once. Returns what happened, for the log and the UI.

    Called from the poller loop, so it inherits the poll interval — a schedule
    cannot react faster than the bridge reads the gateway, which is worth knowing
    before relying on a short window.
    """
    now = now or dt.datetime.now()
    snapshot = snapshot_from_state(state)
    snapshot.update(ha_snapshot(store))     # exposed HA entities are conditions too
    snapshot.update(solar_snapshot(settings))   # weather + solar-forecast sensors
    snapshot.update(nem_snapshot(settings))     # tariff.spot_price (AEMO NEM built-in)
    snapshot.update(ha_price_snapshot(settings, store))   # HA price entity -> tariff.spot_price/feed_in_price (wins over NEM)
    snapshot.update(tariff_snapshot(store, gateway_id, now))   # tariff.* + service.*
    snapshot.update(billing_snapshot(store, gateway_id, now))   # tariff.*_window_active
    from . import billing
    _dyn = apply_dynamic_pricing(snapshot, settings, store, gateway_id)   # per-tariff wholesale override
    snapshot.update(billing.billing_tick(store, gateway_id, snapshot.get("grid.power_w"), now,
                                         dynamic_rate=_dyn))   # demand/energy/bonus/charge (fed here)
    snapshot.update(billing.fixed_snapshot(store, gateway_id, now))   # fixed.* (pure accrual)
    try:
        from . import system_setup
        snapshot.update(system_setup.snapshot(store, settings, gateway_id, host))   # system.* (derived+override)
    except Exception:  # noqa: BLE001
        pass
    snapshot.update(const_snapshot(store))   # const.* automation constants
    # Modbus (SunSpec 702) target: an explicit modbus_host when the poller resolved one
    # (empty string = skip, e.g. a mock with no Modbus); else fall back to host.
    snapshot.update(ratings_snapshot(modbus_host if modbus_host is not None else host))   # ratings.* from Modbus 702 (cached)
    snapshot.update(derived_snapshot(snapshot))   # battery.* derived (needs const.* + ratings.*)
    fired: list[dict] = []
    ready: list[dict] = []
    for entry in store.schedules():
        # A schedule bound to a gateway fires only on THAT gateway's tick, so a
        # battery action targets the right aGate. An unbound schedule (gateway_id
        # empty) fires on the default gateway's tick only, so it is not run once
        # per gateway on a multi-gateway site.
        bound = entry.get("gateway_id") or ""
        if gateway_id is not None:
            if bound and bound != gateway_id:
                continue
            if not bound and not _is_default_gateway(store, gateway_id):
                continue
        dkey = f"{gateway_id or ''}:{entry['id']}"

        # The window can close two ways: time (fire_at + duration elapses) OR an
        # optional EXIT condition tree becoming true mid-window ("end early when…").
        # The effective window is open only while time-inside AND the exit gate is
        # not (yet) satisfied.
        was_inside = _window_inside.get(dkey)
        tt = entry.get("trigger_type") or "daily"
        state, wkey, wend, occ_date = window_now(entry, now)
        cal_ok = _calendar_ok(entry, occ_date)[0]
        if tt == "always":
            # No time window — the entry conditions ARE the window (continuous).
            time_inside = bool(entry.get("enabled") and cal_ok and evaluate(
                entry.get("conditions") or [], snapshot, entry.get("match", "all")))
        else:
            time_inside = bool(entry.get("enabled") and cal_ok and state == "inside")
        entry["_wkey"], entry["_wend"] = wkey, wend
        exit_conds = entry.get("exit_conditions") or []
        exit_now = bool(exit_conds) and time_inside and evaluate(
            exit_conds, snapshot, entry.get("exit_match", "all"))
        effective_inside = time_inside and not exit_now

        # Exit edge: the window was open last tick and has now closed (time OR exit
        # condition) — fire the exit-tagged HA actions once (guarded), regardless of
        # whether the entry action ran, and release a force dispatch as a safety net.
        if was_inside and not effective_inside:
            exit_res = _fire_ha_phase(entry, "exit", settings=settings, client=client,
                                      store=store, snapshot=snapshot, host=host)
            if ((entry.get("action") or {}).get("kind")) == "force":
                exit_res.append(_force_dispatch(
                    entry["action"], host=host, window_min=0, gateway_id=gateway_id,
                    store=store, release=True))
            why = ("exit condition met" if (time_inside and exit_now)
                   else "window closed")
            if exit_res or exit_now:
                store.log_schedule_event(entry["id"], entry["name"], "exit",
                                         (f"{why}: " + "; ".join(exit_res)) if exit_res else why)
        _window_inside[dkey] = effective_inside

        ok, reason = due(entry, now, snapshot, entry.get("last_fired_day"))
        # Do not START a dispatch that the exit gate says should already be closed.
        if ok and exit_now:
            ok, reason = False, "exit condition already holds"
        # 'always' fires on the rising edge only, not every tick while its conditions hold.
        if ok and tt == "always" and was_inside:
            ok, reason = False, "already active"
        if not ok:
            _dwell_since.pop(dkey, None)     # a failing/idle gate resets the hold
            # Audit WHY it did nothing while its window is open — once per day.
            if reason == "entry conditions not met":
                day = now.date().isoformat()
                if _gated_day.get(dkey) != day:
                    _gated_day[dkey] = day
                    store.log_schedule_event(entry["id"], entry["name"], "gated",
                                             gate_reason(entry, snapshot))
            continue
        # Duration hold: conditions must stay true continuously for entry_hold_s.
        hold = int(entry.get("entry_hold_s") or 0)
        if hold > 0:
            started = _dwell_since.get(dkey)
            if started is None:
                started = _dwell_since[dkey] = now
                store.log_schedule_event(
                    entry["id"], entry["name"], "waiting",
                    f"conditions met — holding {hold}s before firing")
            if (now - started).total_seconds() < hold:
                continue
            _dwell_since.pop(dkey, None)
        # Ready to fire — but hold for priority resolution (a higher-priority entry on
        # the same target may pre-empt this one within this same tick).
        ready.append(entry)

    # ── priority resolution ──────────────────────────────────────────────────
    # Entries with a gateway ACTION contend for their target (gateway_id, or the
    # default); the highest priority wins the target for the day, the rest are
    # deferred. Notify-only entries never contend — they always fire.
    contenders: dict[str, list[dict]] = {}
    to_fire: list[dict] = []
    for e in ready:
        if (e.get("action") or {}).get("kind"):
            contenders.setdefault(e.get("gateway_id") or "_default", []).append(e)
        else:
            to_fire.append(e)                       # notify-only: never contends
    # (1) same-tick priority: one winner per target; the rest deferred for the day.
    winners: list[dict] = []
    for tgt, group in contenders.items():
        if len(group) > 1:
            group.sort(key=lambda e: (-int(e.get("priority") or 0), str(e.get("name") or "")))
            for loser in group[1:]:
                detail = (f"deferred — '{group[0]['name']}' (priority {int(group[0].get('priority') or 0)}) "
                          f"pre-empts this on the same target (priority {int(loser.get('priority') or 0)})")
                store.mark_schedule_fired(loser["id"], now.date().isoformat(), "deferred")
                store.log_schedule_event(loser["id"], loser["name"], "deferred", detail)
        winners.append(group[0])
    # (2) conflict with an ACTIVE dispatch already held by ANOTHER schedule (a force
    # dispatch from a previous tick still running). Only force actions hold control.
    try:
        active_owners = {d.get("schedule_id") for d in store.active_dispatches(host=host)}
    except Exception:                                # noqa: BLE001
        active_owners = set()
    active_owners.discard(None)
    for w in winners:
        others = active_owners - {w["id"]}
        if (w.get("action") or {}).get("kind") == "force" and others:
            pol = (w.get("conflict") or "override").lower()
            if pol == "defer":
                store.mark_schedule_fired(w["id"], now.date().isoformat(), "deferred")
                store.log_schedule_event(w["id"], w["name"], "deferred",
                    "deferred — the battery is already under another dispatch (conflict=defer)")
                continue
            if pol == "wait":
                store.log_schedule_event(w["id"], w["name"], "waiting",
                    "waiting — battery busy with another dispatch (conflict=wait); will retry")
                continue                             # not marked fired -> retries next tick
            # override: fall through and take control
        to_fire.append(w)

    for entry in to_fire:
        # Register the run BEFORE attempting it. This is what makes a failure that
        # never produces a log line still visible afterwards: the row exists whether
        # or not anything happens next, so "nothing in the history" stops meaning
        # "we cannot tell".
        occ = _claim_run(entry, store=store, gateway_id=gateway_id, now=now)
        if occ is not None:
            if occ.get("status") in store.OCC_TERMINAL:
                continue                       # already settled this occurrence
            now_ts = now.timestamp()
            if occ.get("status") == "failed" and not retry_due(occ, now_ts):
                continue                       # backing off; the window is still open
            entry["_occ_id"] = occ["id"]
            entry["_occ_attempts"] = int(occ.get("attempts") or 0) + 1
            store.occurrence_attempt(occ["id"], now=now_ts)
        fired.append(_fire_entry(entry, settings=settings, client=client, store=store,
                                 snapshot=snapshot, host=host, gateway_id=gateway_id, now=now))
    return fired


def _claim_run(entry: dict, *, store, gateway_id: str | None, now: dt.datetime):
    """Record this run as expected, and return it. Never raises: a scheduler that
    cannot write its queue must still dispatch, or a bookkeeping fault becomes an
    outage."""
    try:
        wend = entry.get("_wend")
        if wend is None:
            wend = _window_end_ts(entry, now)
        return store.claim_occurrence(
            schedule_id=entry["id"], name=entry.get("name") or "",
            gateway_id=gateway_id or "",
            occurrence_key=entry.get("_wkey") or now.date().isoformat(),
            due_ts=now.timestamp(), window_end_ts=wend, now=now.timestamp())
    except Exception as e:  # noqa: BLE001
        log.warning("could not record the run for %s: %s", entry.get("id"), e)
        return None


#: Retry backoff for a failed run, within its own window. The scheduler ticks every
#: 15s, so retrying on every tick would hammer an unreachable gateway 360 times in a
#: 90-minute window and fill the history with noise. Grows from half a minute to ten.
RETRY_BASE_S = 30.0
RETRY_CAP_S = 600.0


def retry_delay_s(attempts: int) -> float:
    """How long to wait after `attempts` failures before trying again."""
    if attempts <= 0:
        return 0.0
    return min(RETRY_CAP_S, RETRY_BASE_S * (2 ** (attempts - 1)))


def retry_due(occ: dict, now_ts: float) -> bool:
    """Is a previously-failed run ready for another attempt?"""
    last = occ.get("last_attempt_ts")
    if not last:
        return True
    return (now_ts - float(last)) >= retry_delay_s(int(occ.get("attempts") or 0))


def _fire_entry(entry: dict, *, settings, client, store, snapshot: dict,
                host: str | None, gateway_id: str | None, now: dt.datetime) -> dict:
    """Run one entry's gateway action + fire-phase HA actions, mark it fired, and log
    the outcome. Returns the fired-record for the tick's return list."""
    results: list[str] = []
    action = entry.get("action") or {}
    if action.get("kind"):
        results.append(run_action(action, settings=settings, client=client,
                                  store=store, snapshot=snapshot, host=host,
                                  window_min=int(entry.get("duration_min") or 0),
                                  gateway_id=gateway_id, schedule_id=entry["id"],
                                  schedule_name=entry["name"],
                                  window_end_ts=entry.get("_wend") if entry.get("_wend") is not None else _window_end_ts(entry, now)))
    results += _fire_ha_phase(entry, "fire", settings=settings, client=client,
                              store=store, snapshot=snapshot, host=host)
    summary = "; ".join(results) or "nothing to do"
    ok_all = all("failed" not in r and "NOT confirmed" not in r for r in results)

    # Mark the occurrence fired ONLY on success. This is the fix for the defect that
    # started this work: the old code called mark_schedule_fired unconditionally, and
    # due() then refused to re-enter ("already fired this occurrence") — so a two-second
    # Wi-Fi blip at the moment a window opened burned the whole occurrence silently.
    # Leaving it unmarked is the entire retry mechanism: the next tick re-evaluates it,
    # bounded by the window, and sweep_missed closes it out if the window shuts first.
    occ_id = entry.get("_occ_id")
    if ok_all:
        store.mark_schedule_fired(
            entry["id"], entry.get("_wkey") or now.date().isoformat(), summary)
        if occ_id is not None:
            store.finish_occurrence(occ_id, status="ok", outcome=summary)
        store.log_schedule_event(entry["id"], entry["name"], "fired", summary)
    else:
        if occ_id is not None:
            store.finish_occurrence(occ_id, status="failed", reason=summary)
        attempts = int(entry.get("_occ_attempts") or 1)
        store.log_schedule_event(
            entry["id"], entry["name"], "error",
            f"{summary} — attempt {attempts}; retrying in "
            f"{retry_delay_s(attempts):.0f}s while the window is open")
    return {"id": entry["id"], "name": entry["name"], "result": summary,
            "ok": ok_all}
