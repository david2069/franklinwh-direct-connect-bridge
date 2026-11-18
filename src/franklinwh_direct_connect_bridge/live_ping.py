"""Live ping (#730): Network → Latency test → Watch, one round-trip a second until Stop.

One run at a time per gateway: a run claims the gateway with its id on each ping. Another
id is refused while the run is alive; a run that stops pinging (the page was left) frees
the gateway after ``IDLE_S``; a run ends by itself after ``RUN_MAX_S``. Only the Local API
(:9000) is pinged, never the Modbus TCP Server (aGate :502).
"""
from __future__ import annotations

import threading
import time

RUN_MAX_S = 15 * 60
IDLE_S = 5

#: gateway id -> {"id": run id, "started": ts, "seen": ts}
_runs: dict[str, dict] = {}
_lock = threading.Lock()


def claim(runs: dict, gateway_id: str, run_id: str, *, now: float | None = None) -> str:
    """``ok``, ``busy`` (another run holds this gateway) or ``expired`` (past 15 min)."""
    now = time.time() if now is None else now
    cur = runs.get(gateway_id)
    if cur and cur["id"] != run_id and now - cur["seen"] <= IDLE_S:
        return "busy"
    if not cur or cur["id"] != run_id:
        cur = runs[gateway_id] = {"id": run_id, "started": now, "seen": now}
    if now - cur["started"] > RUN_MAX_S:
        runs.pop(gateway_id, None)
        return "expired"
    cur["seen"] = now
    return "ok"


def release(runs: dict, gateway_id: str, run_id: str) -> None:
    cur = runs.get(gateway_id)
    if cur and cur["id"] == run_id:
        runs.pop(gateway_id, None)


def claim_run(gateway_id: str, run_id: str) -> str:
    with _lock:
        return claim(_runs, gateway_id, run_id)


def release_run(gateway_id: str, run_id: str) -> None:
    with _lock:
        release(_runs, gateway_id, run_id)
