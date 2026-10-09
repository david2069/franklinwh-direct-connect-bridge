"""Per-gateway poller supervisor.

The FastAPI lifespan used to hold the poller tasks in a local list with a single shared
stop Event, so a gateway couldn't be stopped without stopping all of them. This keeps a
module-level ``{gw_id: (task, stop)}`` map so enable/disable/add/remove can start or stop
exactly one gateway's poller at runtime (a disable takes effect within one poll interval).
"""
from __future__ import annotations

import asyncio
import logging

from .config import Settings
from .poller import run_gateway
from .state import GatewayState
from .workers import RestartClass, Worker, WorkerState, registry

log = logging.getLogger("franklinwh_direct_connect_bridge.supervisor")

_pollers: dict[str, tuple[asyncio.Task, asyncio.Event]] = {}
_reaping: set[asyncio.Task] = set()   # tasks winding down after stop, kept referenced


def is_running(gw_id: str) -> bool:
    ent = _pollers.get(gw_id)
    return bool(ent and not ent[0].done())


def running_ids() -> list[str]:
    return [k for k in _pollers if is_running(k)]


def worker_name(gw_id: str) -> str:
    return f"poller:{gw_id}"


async def start_poller(settings: Settings, gw: GatewayState) -> None:
    """Start one gateway's poller (idempotent — a running gateway is left alone)."""
    if is_running(gw.id):
        return
    stop = asyncio.Event()
    task = asyncio.create_task(run_gateway(settings, gw, stop))
    _pollers[gw.id] = (task, stop)
    # Register it so a death is noticed (BR-35). HANDOFF: a restarted poller must
    # re-publish discovery and state, or Home Assistant is left holding stale values.
    registry.register(Worker(
        name=worker_name(gw.id),
        concern="read the device, record metrics, publish state",
        cadence_s=float(getattr(settings, "poll_interval", 30) or 30),
        scope=f"gateway:{gw.id}",
        restart_class=RestartClass.HANDOFF,
        kind="task",
    ))._task = task
    registry.beat(worker_name(gw.id), state=WorkerState.RUNNING)
    log.info("poller started for gateway %s (%s)", gw.id, gw.label)


async def stop_poller(gw_id: str) -> None:
    """Signal one gateway's poller to stop and return immediately (a disable toggle must
    not hang the HTTP response). The task exits on its next loop check — setting the stop
    Event wakes its interval wait at once — and is reaped in the background."""
    ent = _pollers.pop(gw_id, None)
    if ent is None:
        return
    task, stop = ent
    stop.set()
    _reaping.add(task)
    task.add_done_callback(_reaping.discard)
    # STOPPED, not FAILED — an intentional stop must never look like a crash, or the
    # supervisor restarts what the operator just switched off.
    registry.beat(worker_name(gw_id), state=WorkerState.STOPPED)
    registry.unregister(worker_name(gw_id))
    log.info("poller stop signalled for gateway %s", gw_id)


async def stop_all() -> None:
    """Shutdown: signal all pollers and await a clean exit (cancel if one overruns)."""
    ents = list(_pollers.items())
    _pollers.clear()
    for gw_id, (_task, stop) in ents:
        stop.set()
        registry.beat(worker_name(gw_id), state=WorkerState.STOPPED)
        registry.unregister(worker_name(gw_id))
    for _gw_id, (task, _stop) in ents:
        try:
            await asyncio.wait_for(task, timeout=35)
        except asyncio.TimeoutError:
            task.cancel()
        except Exception:  # noqa: BLE001
            pass
