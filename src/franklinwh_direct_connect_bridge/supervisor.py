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
    """Is this gateway's poller live *or still winding down*?

    Consults the registry as well as the task map (BR-40). `stop_poller` returns before
    its task exits, so the task map alone said "not running" while the old poller was
    still mid-cycle — and a quick disable→enable then started a second one alongside it.
    """
    ent = _pollers.get(gw_id)
    if ent and not ent[0].done():
        return True
    return registry.name_in_use(worker_name(gw_id)) is not None


def running_ids() -> list[str]:
    return [k for k in _pollers if is_running(k)]


def worker_name(gw_id: str) -> str:
    return f"poller:{gw_id}"


async def start_poller(settings: Settings, gw: GatewayState) -> None:
    """Start one gateway's poller (idempotent — a running gateway is left alone)."""
    if is_running(gw.id):
        prev = registry.name_in_use(worker_name(gw.id))
        if prev is not None and prev.state is WorkerState.STOPPING:
            # Refuse rather than start alongside it. A disable→enable faster than one
            # poll cycle used to produce two pollers for one gateway.
            log.warning("poller for %s is still winding down — not starting a second one",
                        gw.id)
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
        # The restart path IS start_poller: a restarted poller re-publishes discovery
        # and state on its next cycle, which is what HANDOFF means. Nothing bespoke.
        factory=lambda s=settings, g=gw: asyncio.create_task(start_poller(s, g)),
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
    # STOPPING, not STOPPED — the stop has been *requested*, not completed: the loop only
    # checks its event at the end of a cycle and can sit in a read for ~30s. The worker
    # stays registered under its name so nothing can start alongside it, and the
    # supervisor marks it STOPPED and deregisters it once the task has actually finished.
    w = registry.get(worker_name(gw_id))
    if w is not None:
        w.mark_stopping()

        def _reap(_t: asyncio.Task, _name: str = worker_name(gw_id)) -> None:
            """The task finishing is the authoritative end of the stop, so free the
            name here rather than waiting up to a supervisor tick for it. The
            supervisor stays the backstop for a stop that never completes."""
            ww = registry.get(_name)
            if ww is not None and ww.state is WorkerState.STOPPING:
                ww.mark_stopped()
                registry.unregister(_name)

        task.add_done_callback(_reap)
    log.info("poller stop signalled for gateway %s (winding down)", gw_id)


async def stop_all() -> None:
    """Shutdown: signal all pollers and await a clean exit (cancel if one overruns)."""
    ents = list(_pollers.items())
    _pollers.clear()
    for gw_id, (_task, stop) in ents:
        stop.set()
        w = registry.get(worker_name(gw_id))
        if w is not None:
            w.mark_stopping()
    for _gw_id, (task, _stop) in ents:
        try:
            await asyncio.wait_for(task, timeout=35)
        except asyncio.TimeoutError:
            task.cancel()
        except Exception:  # noqa: BLE001
            pass
    for gw_id, _ in ents:
        w = registry.get(worker_name(gw_id))
        if w is not None:
            w.mark_stopped()
        registry.unregister(worker_name(gw_id))
