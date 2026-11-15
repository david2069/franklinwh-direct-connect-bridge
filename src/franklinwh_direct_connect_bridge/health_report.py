"""Scheduled health check, phase 1 (owner 2026-11-15; the Modbus bridge's design, read from
this bridge's own data). Read-only: nothing here talks to an aGate or writes to a battery.

- **Daily snapshot** (``health_daily``): one row per gateway per site day, written on the
  first pass after midnight from that day's stored polls: the aGate's daily counters
  (battery charged and discharged, solar, grid import and export, home load) at their
  last value, the last SoC, and the day's alerts. A row for the bridge itself (gateway
  '') holds the day's alerts and log warnings and errors. Kept for good, so the weekly
  battery report has a trend longer than the purges allow.
- **Daily bridge-health report** (``health_reports``) at 07:00 site time: green, amber or
  red, with the reason on the first line. It looks at the last 24 hours against the 7 days
  before: workers, the gateway link, alerts, log patterns and housekeeping. If the bridge
  was down at 07:00, it runs on the first pass after it starts.

Phase 2: the **weekly battery report**, Monday 07:00 site time, for the week Monday to
Sunday just ended, per gateway, from the daily snapshot: state of health (from the cell
reads the alarm pass already makes, every 5 minutes) and its trend, round-trip efficiency,
full cycles (discharged ÷ the Battery capacity setting), the week's energy, and charge
cycles by depth (rainflow, from the SoC readings). Its level is ``info``: it goes to Home
Assistant, not the phones. Switch: ``health.weekly``.

Where it goes: ``GET /api/health/report``, the Health tab, one Home Assistant notification
that replaces the last (``fwh_dc_health_daily``), and the phones only when it is amber or
red. Both follow the Push notifications switch; the phones also follow their trigger
("Daily health report amber or red"). The report has its own switch, ``health.daily``.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import statistics
import json
import logging
import os
import re
import time
from collections import defaultdict
from collections.abc import Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import rainflow

from . import workers as _workers

log = logging.getLogger(__name__)

DAILY_KEY = "health.daily"
DAILY_AT = (7, 0)                       # site time
NOTIFICATION_ID = "fwh_dc_health_daily"
WEEKLY_KEY = "health.weekly"
WEEKLY_AT = (0, 7, 0)                   # Monday (weekday 0), 07:00 site time
WEEKLY_NOTIFICATION_ID = "fwh_dc_health_weekly"
#: Round-trip efficiency only between two days that end this close in SoC (points)…
EFFICIENCY_SOC_MATCH = 5.0
#: …and with at least this much charged in between, so a quiet week gives no figure.
EFFICIENCY_MIN_WH = 1000.0
#: A SoH trend needs at least this many days between its first and last reading.
SOH_TREND_MIN_DAYS = 28
#: An aPower's SoH counts for the snapshot when read within this long.
SOH_FRESH_S = 86400
#: Cycle depth bands, in SoC points: (label, low, high).
DEPTH_BANDS = (("under 20", 0, 20), ("20 to 50", 20, 50), ("50 to 80", 50, 80),
               ("80 and over", 80, 101))
NOTIFICATION_TITLE = "FranklinWH bridge"
WORKER_NAME = "health_report"
INTERVAL_S = 60.0
REPORT_RETENTION_DAYS = 400

GREEN, AMBER, RED, INFO = "green", "amber", "red", "info"
_RANK = {INFO: 0, GREEN: 0, AMBER: 1, RED: 2}

#: Log patterns: a warning pattern this often in 24 h counts for the colour.
PATTERN_MIN = 10
#: Growing: today more than this many times the 7-day daily average.
GROWING_FACTOR = 2.0
#: Repeating all day: seen in at least this many of the 24 hours.
ALL_DAY_HOURS = 20
#: Link: failed polls at or above this share (of at least LINK_MIN_PROBES) is amber.
LINK_FAIL_SHARE = 0.05
LINK_MIN_PROBES = 100
TOP_PATTERNS = 15
#: An example log line is cut to this.
EXAMPLE_MAX = 300

# Snapshot columns ← the aGate's daily counters (kWh).
_ENERGY = {"battery_charged_wh": "kwh_fhp_chg", "battery_discharged_wh": "kwh_fhp_di",
           "solar_wh": "kwh_sun", "grid_import_wh": "kwh_uti_in",
           "grid_export_wh": "kwh_uti_out", "load_wh": "kwh_load"}

#: A secret in a log line is never copied into a report, which is kept far longer than
#: the log and may be sent to phones.
_SECRET = re.compile(r"(?i)\b(password|passwd|token|secret|api[ _-]?key)"
                     r"(\b[^:=\n]{0,20}?[:=]\s*|\s+)(?!<hidden>)\S+")
_ADDR = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?\b|https?://\S+")
_UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)
_NUM = re.compile(r"\b0x[0-9a-f]+\b|(?<![\w.])[-+]?\d+(?:\.\d+)?", re.I)
_SPACE = re.compile(r"\s+")


def redact(message: str) -> str:
    return _SECRET.sub(lambda m: f"{m.group(1)}{m.group(2)}<hidden>", message or "")


def pattern(message: str) -> str:
    """The message with addresses, ids and numbers taken out, so repeats group."""
    m = _ADDR.sub("<addr>", message or "")
    m = _UUID.sub("<id>", m)
    m = _NUM.sub("<n>", m)
    return _SPACE.sub(" ", m).strip()


def daily_on(store) -> bool:
    return (store.get_config(DAILY_KEY) or "on") != "off"


def set_daily(store, on: bool) -> None:
    store.set_config(DAILY_KEY, "on" if on else "off")
    log.info("Daily health report switched %s", "on" if on else "off")


def weekly_on(store) -> bool:
    return (store.get_config(WEEKLY_KEY) or "on") != "off"


def set_weekly(store, on: bool) -> None:
    store.set_config(WEEKLY_KEY, "on" if on else "off")
    log.info("Weekly battery report switched %s", "on" if on else "off")


def _capacity_setting(store) -> float | None:
    """The Battery capacity setting (Automation), kWh; None when not set."""
    from . import constants
    v = constants.values(store).get("battery_capacity_kwh")
    return float(v) if isinstance(v, (int, float)) and v > 0 else None


_capacity = _capacity_setting


def set_capacity_fn(fn) -> None:
    """Tests: where the capacity comes from."""
    global _capacity
    _capacity = fn


# ── site time ─────────────────────────────────────────────────────────────────
def _zone(store) -> ZoneInfo | None:
    from . import setup_wizard
    name = setup_wizard.site_timezone(store)
    if name:
        try:
            return ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError):
            pass
    return None


def _local(store, now: float) -> dt.datetime:
    """``now`` on the site's clock (aware), else the host's (naive)."""
    tz = _zone(store)
    return dt.datetime.fromtimestamp(now, tz) if tz else dt.datetime.fromtimestamp(now)


def _midnight(d: dt.datetime) -> dt.datetime:
    return d.replace(hour=0, minute=0, second=0, microsecond=0)


def _day(d: dt.datetime) -> str:
    return d.strftime("%Y-%m-%d")


# ── the daily snapshot ────────────────────────────────────────────────────────
def take_snapshot(store, day: str, start: float, end: float, gateway_ids: list[str],
                  now: float, soh_fn: Callable[[str], dict | None] | None = None) -> int:
    """Write ``day``'s rows (``start``..``end`` is that day) where missing. A gateway
    with no poll that day gets no row. ``soh_fn(gateway)``: its aPowers' SoH now
    (``{unit: %}``), averaged into the row. Returns rows written."""
    have = store.health_snapshot_days(day)
    rows = []
    if "" not in have:
        rows.append({"gateway_id": "", "day": day, "ts": now,
                     "alerts": store.count_alerts_opened(start, end),
                     "log_warnings": store.count_logs(start, end, 30, 39),
                     "log_errors": store.count_logs(start, end, 40)})
    for gw in gateway_ids:
        if gw in have:
            continue
        e = store.day_energy(gw, start, end)
        if e is None:
            continue
        row = {"gateway_id": gw, "day": day, "ts": now, "soc": e.get("soc"),
               "alerts": store.count_alerts_opened(start, end, gw)}
        soh = None
        try:
            soh = soh_fn(gw) if soh_fn else None
        except Exception:  # noqa: BLE001 — no SoH is a blank, not a missing row
            soh = None
        if soh:
            row["soh"] = round(statistics.fmean(soh.values()), 2)
        for col, key in _ENERGY.items():
            v = e.get(key)
            row[col] = round(float(v) * 1000, 1) if isinstance(v, (int, float)) else None
        rows.append(row)
    for row in rows:
        store.save_health_snapshot(row)
    return len(rows)


# ── the daily report ──────────────────────────────────────────────────────────
def _log_patterns(store, now: float) -> list[dict]:
    """Warnings and errors of the last 24 h, grouped by pattern, each against its own
    count over the 7 days before."""
    day_start = now - 86400
    groups: dict[tuple[str, str], dict] = {}
    for ts, level_no, name, message in store.problem_logs(now - 8 * 86400, now):
        level = "ERROR" if level_no >= 40 else "WARNING"
        message = redact(message or "")
        if len(message) > EXAMPLE_MAX:
            message = message[:EXAMPLE_MAX - 1] + "…"
        key = (level, pattern(message))
        g = groups.get(key)
        if g is None:
            g = groups[key] = {"level": level, "pattern": key[1], "logger": name or "",
                               "example": message, "count": 0, "prior_7d": 0,
                               "first_ts": None, "last_ts": None, "_hours": set()}
        if ts >= day_start:
            g["count"] += 1
            g["first_ts"] = g["first_ts"] or ts
            g["last_ts"] = ts
            g["example"] = message
            g["_hours"].add(int((ts - day_start) // 3600))
        else:
            g["prior_7d"] += 1
    out = []
    for g in groups.values():
        hours = len(g.pop("_hours"))
        if not g["count"]:
            continue
        g["hours"] = hours
        flags = []
        if not g["prior_7d"]:
            flags.append("new")
        elif g["count"] > GROWING_FACTOR * g["prior_7d"] / 7:
            flags.append("growing")
        if hours >= ALL_DAY_HOURS:
            flags.append("all day")
        g["flags"] = flags
        out.append(g)
    out.sort(key=lambda g: (g["level"] != "ERROR", -g["count"]))
    return out


def _link(store, gw: dict, now: float) -> dict:
    """The gateway's polls (bridge to aGate) over the last 24 h, and failures a day over
    the 7 days before."""
    day: dict = defaultdict(int)
    prior: dict = defaultdict(int)
    for r in store.link_hourly(gw["id"], leg="local_9000", hours=8 * 24, now=now):
        t = day if r["hour_ts"] >= now - 86400 else prior
        for c in ("probes", "ok", "failed", "unknown", "reconnects"):
            t[c] += int(r.get(c) or 0)
    probes = day["probes"]
    return {"gateway": gw["id"], "name": gw["name"],
            **{c: day[c] for c in ("probes", "ok", "failed", "unknown", "reconnects")},
            "failed_share": round(day["failed"] / probes, 4) if probes else None,
            "prior_7d_failed_per_day": round(prior["failed"] / 7, 1)}


def grade(report: dict) -> tuple[str, list[str]]:
    """``(level, reasons)``, worst first.

    - **Red:** a worker crashed or stopped beating; a critical condition still active
      (one that cleared but nobody acknowledged doesn't count).
    - **Amber:** a warning condition still active; any error in the log; a warning
      pattern seen at least ``PATTERN_MIN`` times that is new, growing or all day; a
      gateway with 5 % or more of its polls failed (of at least 100).
    - **Green:** none of those.
    """
    found: list[tuple[str, str]] = []
    w = report["workers"]
    for name in w["broken"]:
        found.append((RED, f"worker {name} {w['states'].get(name, 'broken')}"))
    for name in w["stale"]:
        if name not in w["broken"]:
            found.append((RED, f"worker {name} stopped beating"))
    for al in report["alerts"]["open"]:
        where = f" ({al['gateway']})" if al.get("gateway") else ""
        found.append((RED if al["severity"] == "critical" else AMBER,
                      f"alert open: {al['title']}{where}"))
    for p in report["logs"]["patterns"]:
        if p["level"] == "ERROR":
            found.append((AMBER, f"{p['count']} × error: {p['example'][:120]}"))
        elif p["flags"] and p["count"] >= PATTERN_MIN:
            found.append((AMBER, f"{p['count']} × warning ({', '.join(p['flags'])}): "
                                 f"{p['example'][:120]}"))
    for g in report["link"]:
        share = g.get("failed_share")
        if share is not None and g["probes"] >= LINK_MIN_PROBES and share >= LINK_FAIL_SHARE:
            found.append((AMBER, f"{g['name']}: {share:.0%} of polls failed"))
    found.sort(key=lambda f: -_RANK[f[0]])
    return (found[0][0] if found else GREEN), [r for _, r in found]


def _headline(level: str, reasons: list[str], report: dict) -> str:
    if reasons:
        more = f" (+{len(reasons) - 1} more)" if len(reasons) > 1 else ""
        return f"{level.capitalize()}: {reasons[0]}{more}"
    return (f"Green: all {report['workers']['count']} workers running, no alert open, "
            f"{report['logs']['warnings']} warnings in 24 h")


def build_daily(store, now: float, *, registry=None, gateways: list[dict],
                backups_fn: Callable[[], list] | None = None) -> dict:
    """The daily bridge-health report as a dict (not stored). ``gateways`` are the
    enabled ones, ``{id, name}``."""
    since = now - 86400
    snap = (registry or _workers.registry).snapshot()
    states = {w["name"]: ("crashed" if w["state"] == "crashed" else w["state"])
              for w in snap["workers"]}

    raised: dict[str, dict] = {}
    for al in store.alerts(since=since, limit=500):
        r = raised.setdefault(al["code"], {"code": al["code"], "title": al["title"],
                                           "severity": al["severity"], "alerts": 0,
                                           "repeats": 0})
        r["alerts"] += 1
        r["repeats"] += int(al.get("count") or 1)
    # Still active only: a condition that cleared overnight must not turn the report red,
    # though the Alerts bar keeps it until someone acknowledges it.
    open_now = [{"id": al["id"], "code": al["code"], "title": al["title"],
                 "severity": al["severity"], "gateway": al["gateway_id"],
                 "opened_ts": al["opened_ts"]}
                for al in store.alerts(open_only=True, kind="condition", limit=500)
                if al.get("resolved_ts") is None]

    patterns = _log_patterns(store, now)
    house: dict = {"db_bytes": None, "log_rows": store.logs_count(), "last_backup_ts": None}
    if store.path != ":memory:":
        house["db_bytes"] = sum(os.path.getsize(p) for p in (store.path, store.path + "-wal")
                                if os.path.exists(p))
    if backups_fn is not None:
        try:
            bl = backups_fn()
            house["last_backup_ts"] = max(b["mtime"] for b in bl) if bl else None
        except Exception:  # noqa: BLE001 — housekeeping is a footnote, not a failure
            pass

    report = {
        "kind": "daily",
        "window": {"from": since, "to": now},
        "workers": {"count": len(snap["workers"]), "broken": snap["broken"],
                    "stale": snap["stale"], "states": states,
                    "restarts": sum(int(w.get("restarts") or 0) for w in snap["workers"])},
        "link": [_link(store, g, now) for g in gateways],
        "alerts": {"raised": sorted(raised.values(), key=lambda r: -r["repeats"]),
                   "open": open_now},
        "logs": {"warnings": sum(p["count"] for p in patterns if p["level"] == "WARNING"),
                 "errors": sum(p["count"] for p in patterns if p["level"] == "ERROR"),
                 "pattern_count": len(patterns), "patterns": patterns[:TOP_PATTERNS]},
        "housekeeping": house,
    }
    level, reasons = grade(report)
    report.update(level=level, reasons=reasons, headline=_headline(level, reasons, report))
    return report


# ── the weekly battery report (phase 2) ──────────────────────────────────────
def _days_between(a: str, b: str) -> int:
    return (dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days


def _nearest(rows: list[dict], day: str, col: str, within: int) -> dict | None:
    """The row with ``col`` closest to ``day``, at most ``within`` days from it."""
    best = None
    for r in rows:
        if r.get(col) is None:
            continue
        d = abs(_days_between(r["day"], day))
        if d <= within and (best is None or d < best[0]):
            best = (d, r)
    return best[1] if best else None


def efficiency(rows: list[dict]) -> dict | None:
    """Round-trip efficiency, battery energy out ÷ in, over the longest span among
    ``rows`` (oldest first, one a day) whose two end-of-day SoCs are within
    ``EFFICIENCY_SOC_MATCH`` points, so the charge left in the battery hardly counts. The
    span's energy is the daily totals of the days after its first. None without one."""
    usable = [r for r in rows if None not in (r.get("soc"), r.get("battery_charged_wh"),
                                              r.get("battery_discharged_wh"))]
    best = None
    for i, a in enumerate(usable):
        for j in range(i + 1, len(usable)):
            b = usable[j]
            if abs(b["soc"] - a["soc"]) > EFFICIENCY_SOC_MATCH:
                continue
            days = usable[i + 1:j + 1]
            if any(_days_between(x["day"], y["day"]) != 1 for x, y in zip([a] + days, days)):
                continue                        # a day missing in between: no honest sum
            charged = sum(r["battery_charged_wh"] for r in days)
            out = sum(r["battery_discharged_wh"] for r in days)
            if charged < EFFICIENCY_MIN_WH:
                continue
            span = _days_between(a["day"], b["day"])
            if best is None or span > best["days"]:
                best = {"pct": round(100 * out / charged, 1), "days": span, "from": a["day"],
                        "to": b["day"], "soc_from": a["soc"], "soc_to": b["soc"],
                        "in_kwh": round(charged / 1000, 2), "out_kwh": round(out / 1000, 2)}
    return best


def soc_cycles(socs: list[float]) -> dict:
    """Charge cycles from a SoC series, counted by rainflow (ASTM E1049-85): how many, how
    deep on average, and how many in each depth band. Half cycles count 0.5."""
    series = [float(v) for v in socs if v is not None]
    bands = {b[0]: 0.0 for b in DEPTH_BANDS}
    if len(series) < 3:
        return {"cycles": 0.0, "mean_depth": None, "bands": bands}
    total = depth_sum = 0.0
    for depth, n in rainflow.count_cycles(series):
        if depth < 1:                           # SoC noise, not a cycle
            continue
        total += n
        depth_sum += depth * n
        for label, lo, hi in DEPTH_BANDS:
            if lo <= depth < hi:
                bands[label] += n
    return {"cycles": round(total, 1), "mean_depth": round(depth_sum / total, 1) if total else None,
            "bands": {k: round(v, 1) for k, v in bands.items()}}


_ENERGY_KWH = (("battery_in_kwh", "battery_charged_wh"), ("battery_out_kwh", "battery_discharged_wh"),
               ("grid_import_kwh", "grid_import_wh"), ("grid_export_kwh", "grid_export_wh"),
               ("solar_kwh", "solar_wh"), ("home_kwh", "load_wh"))


def build_weekly(store, now: float, *, gateways: list[dict]) -> dict:
    """The weekly battery report for the week (Monday to Sunday) before ``now``'s week."""
    local = _local(store, now)
    this_monday = _midnight(local) - dt.timedelta(days=local.weekday())
    monday, sunday = this_monday - dt.timedelta(days=7), this_monday - dt.timedelta(days=1)
    first, last = _day(monday - dt.timedelta(days=1)), _day(sunday)
    cap = _capacity(store)
    sections = []
    for g in gateways:
        history = sorted((r for r in store.health_snapshots(g["id"], days=400)
                          if r["day"] <= last), key=lambda r: r["day"])
        span = [r for r in history if first <= r["day"] <= last]      # Sunday before … Sunday
        week = [r for r in span if r["day"] >= _day(monday)]
        sec: dict = {"gateway": g["id"], "name": g["name"], "days": len(week)}
        now_r = _nearest(history, last, "soh", 7)
        soh = {"now": now_r and now_r["soh"], "day": now_r and now_r["day"], "per_month": None}
        for key, back, within in (("week_ago", 7, 3), ("four_weeks_ago", 28, 7), ("year_ago", 365, 14)):
            r = _nearest(history, _day(sunday - dt.timedelta(days=back)), "soh", within)
            soh[key] = r and r["soh"]
        with_soh = [r for r in history if r.get("soh") is not None and _days_between(r["day"], last) <= 365]
        if len(with_soh) >= 2 and _days_between(with_soh[0]["day"], with_soh[-1]["day"]) >= SOH_TREND_MIN_DAYS:
            soh["per_month"] = round((with_soh[-1]["soh"] - with_soh[0]["soh"])
                                     / _days_between(with_soh[0]["day"], with_soh[-1]["day"]) * 30, 2)
        sec["soh"] = soh
        sec["energy"] = ({k: round(sum(r[c] or 0 for r in week) / 1000, 2) for k, c in _ENERGY_KWH}
                         if week else None)
        sec["efficiency"] = efficiency(span)
        out_kwh = sec["energy"] and sec["energy"]["battery_out_kwh"]
        sec["full_cycles"] = {"week": round(out_kwh / cap, 2) if out_kwh is not None and cap else None,
                              "capacity_kwh": cap}
        if not cap:
            sec["full_cycles"]["needs"] = "battery capacity"
        sec["cycles"] = soc_cycles(store.soc_series(g["id"], monday.timestamp(),
                                                    this_monday.timestamp()))
        sections.append(sec)
    parts = []
    for sec in sections:
        bits = []
        if sec["soh"]["now"] is not None:
            bits.append(f"SoH {round(sec['soh']['now'], 1):g}%")
        if sec["efficiency"]:
            bits.append(f"efficiency {sec['efficiency']['pct']:g}%")
        if sec["full_cycles"]["week"] is not None:
            bits.append(f"{sec['full_cycles']['week']:g} full cycles")
        if not bits:
            bits.append("not enough daily snapshots yet")
        parts.append((f"{sec['name']}: " if len(sections) > 1 else "") + ", ".join(bits))
    headline = (f"Week of {monday.day} {monday:%b}: "
                + ("; ".join(parts) if parts else "no gateway configured"))
    return {"kind": "weekly", "week": {"from": _day(monday), "to": _day(sunday)},
            "gateways": sections, "level": INFO, "reasons": [], "headline": headline}


def notification_text(report: dict) -> tuple[str, str]:
    """``(title, message)``: the headline, then the other reasons."""
    if report["kind"] == "weekly":
        return (f"{NOTIFICATION_TITLE}: weekly battery report",
                f"{report['headline']}\nOpen the bridge → Health for the full report.")
    title = f"{NOTIFICATION_TITLE}: health {report['level']}"
    lines = [report["headline"]]
    lines += [f"- {r}" for r in report["reasons"][1:6]]
    if len(report["reasons"]) > 6:
        lines.append(f"- and {len(report['reasons']) - 6} more")
    lines.append("Open the bridge → Health for the full report.")
    return title, "\n".join(lines)


# ── the job ───────────────────────────────────────────────────────────────────
def _phones(store, title: str, message: str) -> None:
    from . import notify_engine
    notify_engine.fire(store, "health_report", title=title, message=message)


def run(store, now: float, *, registry=None, gateways: list[dict], notifier=None,
        backups_fn=None, period: str | None = None, kind: str = "daily") -> dict:
    """Build, store and (with a ``notifier``) send a report: today's daily one, or the
    weekly one for last week (its period is that week's Monday)."""
    if kind == "weekly":
        report = build_weekly(store, now, gateways=gateways)
        period = report["week"]["from"]
    else:
        report = build_daily(store, now, registry=registry, gateways=gateways,
                             backups_fn=backups_fn)
        period = period or _day(_local(store, now))
    rid = store.save_health_report(kind, period, now, report["level"], report["headline"],
                                   json.dumps(report), REPORT_RETENTION_DAYS)
    log.info("%s report: %s", "Weekly battery" if kind == "weekly" else "Daily health",
             report["headline"])
    if notifier is not None:
        _deliver(store, report, now, notifier)
    return {"id": rid, "ts": now, "period": period, "level": report["level"],
            "headline": report["headline"], "report": report}


def _deliver(store, report: dict, now: float, notifier) -> None:
    """The HA notification, replacing the last, and for amber or red the phones. Both
    follow the Push notifications switch. Never raises."""
    title, message = notification_text(report)
    try:
        stamp = _local(store, now).strftime("%d %b %H:%M")
        err = notifier.call_service("persistent_notification", "create", {
            "notification_id": WEEKLY_NOTIFICATION_ID if report["kind"] == "weekly"
            else NOTIFICATION_ID, "title": title,
            "message": f"{message}\n\n{stamp}"})
        if err:
            log.info("Health report not sent to Home Assistant: %s", err)
        if report["level"] in (AMBER, RED):
            _phones(store, title, message)
    except Exception as e:  # noqa: BLE001 — a report never breaks the job
        log.info("Health report not sent: %s", str(e) or type(e).__name__)


def tick(store, *, now: float | None = None, registry=None, gateways: list[dict],
         notifier=None, backups_fn=None, soh_fn=None) -> dict | None:
    """One pass: yesterday's snapshot if missing; today's report if it is due; on Monday
    from 07:00, last week's battery report if it isn't made yet."""
    now = time.time() if now is None else now
    local = _local(store, now)
    today = _midnight(local)
    yesterday = _midnight(today - dt.timedelta(hours=12))
    take_snapshot(store, _day(yesterday), yesterday.timestamp(), today.timestamp(),
                  [g["id"] for g in gateways], now, soh_fn=soh_fn)
    out = None
    due = today.replace(hour=DAILY_AT[0], minute=DAILY_AT[1])
    if local >= due and daily_on(store) and not store.has_health_report("daily", _day(local)):
        out = run(store, now, registry=registry, gateways=gateways, notifier=notifier,
                  backups_fn=backups_fn, period=_day(local))
    monday = today - dt.timedelta(days=today.weekday())
    due = monday.replace(hour=WEEKLY_AT[1], minute=WEEKLY_AT[2])
    if local >= due and weekly_on(store) \
            and not store.has_health_report("weekly", _day(monday - dt.timedelta(days=7))):
        out = run(store, now, gateways=gateways, notifier=notifier, kind="weekly")
    return out


def _soh_now(gateway_id: str) -> dict | None:
    """The gateway's aPowers' SoH from the alarm pass, when read in the last day."""
    from . import state
    gw = state.get_gateway(gateway_id)
    if gw is None or time.time() - (getattr(gw, "device_alarms_ts", 0.0) or 0.0) > SOH_FRESH_S:
        return None
    return getattr(gw, "apower_soh", None) or None


def enabled_gateways(store) -> list[dict]:
    return [{"id": g["id"], "name": g.get("name") or g.get("label") or g["id"]}
            for g in store.gateways() if g.get("enabled", 1)]


class HealthReporter:
    """The built-in job, one pass a minute. Registered as a Worker."""

    def __init__(self, *, store_fn, notifier, backups_fn=None, registry=None) -> None:
        self.store_fn = store_fn
        self.notifier = notifier
        self.backups_fn = backups_fn
        self.registry = registry or _workers.registry

    def run_once(self) -> dict | None:
        store = self.store_fn()
        if store is None:
            return None
        return tick(store, registry=self.registry, gateways=enabled_gateways(store),
                    notifier=self.notifier, backups_fn=self.backups_fn, soh_fn=_soh_now)

    async def run(self, stop: asyncio.Event) -> None:
        w = self.registry.register(_workers.Worker(
            name=WORKER_NAME, concern="daily snapshot and health report",
            cadence_s=INTERVAL_S, restart_class=_workers.RestartClass.FREE, kind="task"))
        w._task = asyncio.current_task()
        while not stop.is_set():
            w.beat(state=_workers.WorkerState.RUNNING)
            try:
                await asyncio.to_thread(self.run_once)
            except Exception as e:  # noqa: BLE001 — the next pass tries again
                log.warning("Health check pass failed: %s", e)
            try:
                await asyncio.wait_for(stop.wait(), timeout=INTERVAL_S)
            except asyncio.TimeoutError:
                pass
        w.mark_stopped()
