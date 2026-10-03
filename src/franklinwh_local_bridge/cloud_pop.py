"""CloudFront PoP edge metrics (FEAT-CLOUD-POP-METRICS).

The ``franklinwh-cloud`` library already tracks CloudFront edge headers per response
(``EdgeTracker`` → ``cloud.get_metrics()['edge']``). Each background cloud poll creates a fresh
client, so its snapshot reflects THAT poll's handful of requests. We persist one sample per poll
and aggregate over a retention window into the FWHAI-style view: current PoP, distribution,
transitions (the edge re-homes over time), and cache-hit rate. On-LAN, no extra cloud traffic —
it rides the existing VPP/run-status poll.
"""
from __future__ import annotations

import time
from typing import Any


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
            trace_id=edge.get("last_cf_trace_id"))
    except Exception:  # noqa: BLE001
        pass


def summary(store, *, window_days: int = 30, max_transitions: int = 30) -> dict[str, Any]:
    """Aggregate persisted samples into the drill-down: current PoP, distribution, transitions
    (newest first), cache-hit rate, totals. ``configured:false`` when the store is unavailable."""
    if store is None:
        return {"configured": False}
    since = time.time() - window_days * 86400
    try:
        rows = store.cloud_pop_samples(since_ts=since) or []
    except Exception:  # noqa: BLE001
        rows = []
    if not rows:
        return {"configured": True, "samples": 0, "current_pop": None, "distribution": {},
                "transitions": [], "transition_count": 0, "total_requests": 0,
                "cache_hit_rate": None, "window_days": window_days}
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
            transitions.append({"from": prev, "to": pop, "at": r.get("ts")})
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
        "window_days": window_days,
    }
