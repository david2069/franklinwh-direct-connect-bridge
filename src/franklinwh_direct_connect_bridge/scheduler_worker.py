"""The scheduler as a component, not a passenger (RUNTIME_DESIGN phase 1).

`scheduler.tick` used to run inside the gateway poll loop. That had two consequences,
neither intended:

* the scheduler **inherited the poll interval** as its resolution, so a schedule could
  not react faster than the bridge happened to read the gateway;
* it **died with its host** — one gateway's poller ending stopped *all* scheduling,
  silently, because nothing supervised either of them.

It now runs on its own fixed cadence, evaluating every gateway each tick from the
snapshot that gateway's poller last wrote.

Decoupling introduces a hazard that the coupled version could not have: a scheduler
outliving its poller would keep evaluating conditions against a snapshot that stopped
being updated hours ago — a schedule firing on a stale SoC. So freshness is enforced
here from the start, rather than waiting for the full capability-health model in phase 4:
a gateway whose snapshot has aged out is **skipped with a reason**, never evaluated.
"""
from __future__ import annotations

import asyncio
import logging
import time

from . import scheduler as _sched
from . import workers as _workers
from .config import Settings
from .db import get_store
from .state import gateways as get_gateways

log = logging.getLogger(__name__)

WORKER_NAME = "scheduler"

#: A snapshot older than this is not a basis for deciding anything. Generous — three
#: poll intervals, floored — because a single slow poll is normal and refusing to
#: schedule is itself a failure.
def staleness_limit_s(settings: Settings) -> float:
    return max(90.0, float(getattr(settings, "poll_interval", 30) or 30) * 3.0)


def snapshot_age_s(gw, now: float | None = None) -> float:
    """Age of this gateway's state snapshot. A gateway that has never polled is
    infinitely old, not fresh — the absence of data is not evidence of health."""
    if not getattr(gw, "state_ts", 0):
        return float("inf")
    return (now if now is not None else time.time()) - gw.state_ts


def eligible(gw, settings: Settings, now: float | None = None) -> tuple[bool, str]:
    """May this gateway's schedules be evaluated right now? Returns (ok, reason)."""
    if not getattr(gw, "enabled", True):
        return False, "gateway disabled"
    age = snapshot_age_s(gw, now)
    if age == float("inf"):
        return False, "no state snapshot yet"
    limit = staleness_limit_s(settings)
    if age > limit:
        return False, f"snapshot is {age:.0f}s old (limit {limit:.0f}s) — not evaluating"
    return True, ""


def _context(gw) -> dict:
    """What `scheduler.tick` needs about one gateway. Mocks have no Modbus, so the
    ratings read is skipped by passing an empty modbus host."""
    known_host = getattr(gw, "active_host", None) or getattr(gw, "configured_host", None)
    return {
        "state": gw.last_state or {},
        "host": known_host,
        "modbus_host": "" if getattr(gw, "is_mock", False) else known_host,
        "gateway_id": gw.id,
    }


def tick_once(settings: Settings, *, client, now: float | None = None) -> list[dict]:
    """Evaluate every eligible gateway once. Never raises: one gateway's failure must
    not stop the others, which was the whole problem with the coupled version."""
    store = get_store(settings)
    if store is None:
        return []
    fired: list[dict] = []
    for gw in get_gateways():
        ok, why = eligible(gw, settings, now)
        if not ok:
            log.debug("[%s] schedules not evaluated: %s", gw.id, why)
            continue
        try:
            fired += [dict(f, gateway_id=gw.id) for f in _sched.tick(
                settings=settings, client=client, store=store, **_context(gw))]
        except Exception as e:  # noqa: BLE001 — one gateway must not stop the rest
            log.warning("[%s] scheduler tick failed: %s", gw.id, e)
    return fired


async def run(settings: Settings, stop: asyncio.Event, *, client) -> None:
    """The scheduler worker loop. Registered and supervised like any other worker."""
    cadence = max(5, int(getattr(settings, "scheduler_tick_s", 15) or 15))
    w = _workers.registry.register(_workers.Worker(
        name=WORKER_NAME,
        concern="evaluate schedules and run due work",
        cadence_s=float(cadence),
        restart_class=_workers.RestartClass.FREE,
        kind="task",
    ))
    w.state = _workers.WorkerState.READY
    log.info("scheduler worker started (every %ds, independent of poll interval)", cadence)
    try:
        while not stop.is_set():
            w.beat(state=_workers.WorkerState.RUNNING)
            try:
                for f in await asyncio.to_thread(tick_once, settings, client=client):
                    log.info("[%s] schedule '%s' fired: %s",
                             f.get("gateway_id", "?"), f["name"], f["result"])
            except Exception as e:  # noqa: BLE001 — never let one bad tick kill the loop
                log.warning("scheduler tick failed: %s", e)
            try:
                await asyncio.wait_for(stop.wait(), timeout=cadence)
            except asyncio.TimeoutError:
                pass
    except asyncio.CancelledError:
        raise
    finally:
        w.mark_stopped()
        _workers.registry.unregister(WORKER_NAME)
        log.info("scheduler worker stopped")
