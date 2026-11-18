"""CloudFront PoP edge metrics (FEAT-CLOUD-POP-METRICS).

The ``franklinwh-cloud`` library already tracks CloudFront edge headers per response
(``EdgeTracker`` → ``cloud.get_metrics()['edge']``). Each background cloud poll creates a fresh
client, so its snapshot reflects THAT poll's handful of requests. We persist one sample per poll
and aggregate over a retention window into the FWHAI-style view: current PoP, distribution,
transitions (the edge re-homes over time), and cache-hit rate. On-LAN, no extra cloud traffic —
it rides the existing VPP/run-status poll.
"""
from __future__ import annotations

import json
import time
from typing import Any

#: The franklinwh-cloud ``get_metrics()`` call counters kept per poll (Network → Cloud
#: requests). Each poll uses a fresh Client, so a snapshot is that poll's counts.
API_COUNTERS = ("total_api_calls", "total_errors", "retry_count", "token_refresh_count",
                "login_count")
API_DICTS = ("calls_by_method", "errors_by_type")

#: Network → Cloud requests period choices. Samples are kept 30 days, so "all" is
#: everything kept. ``None`` = since local midnight; ``0`` = no lower bound.
PERIODS = {"today": None, "7d": 7, "30d": 30, "all": 0}

#: CloudFront PoP codes start with the nearest airport's IATA code (SYD62-P1 = Sydney).
#: Where each is, for the Network PoP map. A code not listed here is shown in the table
#: but not plotted.
POP_CITIES: dict[str, tuple[str, float, float]] = {
    "SYD": ("Sydney", -33.87, 151.21), "BNE": ("Brisbane", -27.47, 153.03),
    "MEL": ("Melbourne", -37.81, 144.96), "PER": ("Perth", -31.95, 115.86),
    "ADL": ("Adelaide", -34.93, 138.60), "AKL": ("Auckland", -36.85, 174.76),
    "LAX": ("Los Angeles", 34.05, -118.24), "SFO": ("San Francisco", 37.77, -122.42),
    "SEA": ("Seattle", 47.61, -122.33), "MIA": ("Miami", 25.76, -80.19),
    "IAD": ("Washington DC", 38.95, -77.45), "JFK": ("New York", 40.71, -74.01),
    "EWR": ("Newark", 40.74, -74.17), "ORD": ("Chicago", 41.88, -87.63),
    "DFW": ("Dallas", 32.78, -96.80), "ATL": ("Atlanta", 33.75, -84.39),
    "DEN": ("Denver", 39.74, -104.99), "PHX": ("Phoenix", 33.45, -112.07),
    "BOS": ("Boston", 42.36, -71.06), "IAH": ("Houston", 29.76, -95.37),
    "YVR": ("Vancouver", 49.28, -123.12), "YTO": ("Toronto", 43.65, -79.38),
    "YUL": ("Montreal", 45.50, -73.57), "SIN": ("Singapore", 1.35, 103.82),
    "NRT": ("Tokyo", 35.68, 139.69), "KIX": ("Osaka", 34.69, 135.50),
    "HKG": ("Hong Kong", 22.32, 114.17), "ICN": ("Seoul", 37.57, 126.98),
    "TPE": ("Taipei", 25.03, 121.57), "BOM": ("Mumbai", 19.08, 72.88),
    "LHR": ("London", 51.51, -0.13), "FRA": ("Frankfurt", 50.11, 8.68),
    "AMS": ("Amsterdam", 52.37, 4.90), "CDG": ("Paris", 48.86, 2.35),
}


def pop_location(pop: str | None) -> dict | None:
    """``{city, lat, lon}`` for a PoP code by its IATA prefix, or None when unknown."""
    code = "".join(ch for ch in (pop or "")[:3] if ch.isalpha()).upper()
    hit = POP_CITIES.get(code)
    return {"city": hit[0], "lat": hit[1], "lon": hit[2]} if hit else None


def api_counters(metrics: dict | None) -> dict | None:
    """Only the call counters from a ``get_metrics()`` snapshot, or None."""
    if not isinstance(metrics, dict):
        return None
    out: dict[str, Any] = {}
    for k in API_COUNTERS:
        if isinstance(metrics.get(k), (int, float)):
            out[k] = int(metrics[k])
    for k in API_DICTS:
        if isinstance(metrics.get(k), dict):
            out[k] = {str(n): int(v) for n, v in metrics[k].items() if isinstance(v, (int, float))}
    return out or None


def ingest(store, edge: dict | None) -> None:
    """Persist one poll's CloudFront edge snapshot (from ``cloud.get_metrics()['edge']``).
    Best-effort — never raises, never blocks the caller's cloud poll."""
    if store is None or not isinstance(edge, dict):
        return
    pop = edge.get("current_pop")
    if not pop:
        return
    try:
        store.record_cloud_pop(
            pop=pop,
            requests=int(edge.get("total_cf_requests") or 0),
            hits=int(edge.get("cache_hits") or 0),
            misses=int(edge.get("cache_misses") or 0),
            trace_id=edge.get("last_cf_trace_id"),
            api=edge.get("api") if isinstance(edge.get("api"), dict) else None)
    except Exception:  # noqa: BLE001
        pass


def _sum_api(rows: list[dict]) -> dict | None:
    """The kept call counters summed over ``rows``; None when no sample has them."""
    tot: dict[str, Any] = {"samples": 0, **{k: 0 for k in API_COUNTERS},
                           **{k: {} for k in API_DICTS}}
    for r in rows:
        raw = r.get("api")
        try:
            api = json.loads(raw) if isinstance(raw, str) else None
        except ValueError:
            api = None
        if not isinstance(api, dict):
            continue
        tot["samples"] += 1
        for k in API_COUNTERS:
            tot[k] += int(api.get(k) or 0)
        for k in API_DICTS:
            for n, v in (api.get(k) or {}).items():
                tot[k][n] = tot[k].get(n, 0) + int(v or 0)
    return tot if tot["samples"] else None


def summary(store, *, window_days: int = 30, max_transitions: int = 30,
            period: str | None = None) -> dict[str, Any]:
    """Aggregate persisted samples into the drill-down: current PoP, distribution, transitions
    (newest first), cache-hit rate, totals, and the cloud call counters (``api``).
    ``period`` (today / 7d / 30d) overrides ``window_days``; today starts at local midnight.
    ``configured:false`` when the store is unavailable."""
    if store is None:
        return {"configured": False}
    if period in PERIODS:
        if PERIODS[period] is None:
            lt = time.localtime()
            since = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))
            window_days = 1
        elif PERIODS[period] == 0:
            since = 0.0
        else:
            window_days = PERIODS[period]
            since = time.time() - window_days * 86400
    else:
        period = None
        since = time.time() - window_days * 86400
    try:
        rows = store.cloud_pop_samples(since_ts=since) or []
    except Exception:  # noqa: BLE001
        rows = []
    if not rows:
        return {"configured": True, "samples": 0, "current_pop": None, "distribution": {},
                "transitions": [], "transition_count": 0, "total_requests": 0,
                "cache_hit_rate": None, "window_days": window_days, "period": period,
                "api": None, "locations": {}}
    dist: dict[str, int] = {}
    total = hits = misses = 0
    transitions: list[dict] = []
    prev = None
    for r in rows:
        pop = r.get("pop")
        req = int(r.get("requests") or 0) or 1              # at least count the poll itself
        dist[pop] = dist.get(pop, 0) + req
        total += req
        hits += int(r.get("hits") or 0)
        misses += int(r.get("misses") or 0)
        if prev is not None and pop != prev:
            # stay_s: how long the edge was on ``from`` (since the change that brought it
            # there); None when that change is before the period's first sample.
            at = r.get("ts")
            last = transitions[-1]["at"] if transitions else None
            transitions.append({"from": prev, "to": pop, "at": at,
                                "stay_s": (round(at - last) if last is not None else None)})
        prev = pop
    cache_total = hits + misses
    return {
        "configured": True, "samples": len(rows),
        "current_pop": rows[-1].get("pop"),
        "distribution": dict(sorted(dist.items(), key=lambda kv: -kv[1])),
        "transitions": transitions[-max_transitions:][::-1],   # newest first
        "transition_count": len(transitions),
        "total_requests": total, "cache_hits": hits, "cache_misses": misses,
        "cache_hit_rate": (round(100 * hits / cache_total, 1) if cache_total else None),
        "window_days": window_days, "period": period,
        "api": _sum_api(rows),
        "locations": {pp: pop_location(pp) for pp in dist},
    }
