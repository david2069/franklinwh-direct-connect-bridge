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
from .workers import abort as workers_abort

log = logging.getLogger("franklinwh_direct_connect_bridge.supervisor")

_pollers: dict[str, tuple[asyncio.Task, asyncio.Event]] = {}
_reaping: set[asyncio.Task] = set()   # tasks winding down after stop, kept referenced
#: gw_id -> the old poller task still winding down after stop_poller (#82).
_stopping: dict[str, asyncio.Task] = {}
#: gw_id -> a start that is waiting for that old task to finish (#82).
_deferred: dict[str, asyncio.Task] = {}
#: How long a deferred start waits for the old poller before aborting it. A poll cycle
#: can sit in a device read for ~30 s; stop_all allows 35 s for the same reason.
DEFER_WAIT_S = 40.0
#: How long shutdown waits for each poller before aborting it.
STOP_GRACE_S = 35.0
#: Set while stop_all runs: no poller starts during shutdown, deferred or not (#681).
_shutting_down = False


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
    if _shutting_down:
        log.debug("not starting the poller for %s: the bridge is shutting down", gw.id)
        return
    if is_running(gw.id):
        prev = registry.name_in_use(worker_name(gw.id))
        if prev is not None and prev.state is WorkerState.STOPPING:
            # Never start alongside it (a disable→enable faster than one poll cycle used
            # to produce two pollers), but never DROP the start either: refusing with no
            # retry left an edited gateway with no poller until the add-on restarted, its
            # HA entities stuck "unavailable" (#82). Start as soon as the old one is gone.
            _defer_start(settings, gw)
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


def _defer_start(settings: Settings, gw: GatewayState) -> None:
    """Start ``gw``'s poller once its predecessor has finished. Idempotent per gateway."""
    pending = _deferred.get(gw.id)
    if pending is not None and not pending.done():
        return
    old = _stopping.get(gw.id)
    if old is None:
        # Stopped without being listed as winding down (stop_all does that): wait on the
        # worker's own task, never on nothing. Waiting on nothing re-deferred at once,
        # forever (#681).
        w = registry.get(worker_name(gw.id))
        old = w._task if w is not None else None

    async def _later() -> None:
        try:
            if old is not None and not old.done():
                done, _ = await asyncio.wait({old}, timeout=DEFER_WAIT_S)
                if not done:
                    # The old poller overran its stop. Abort it (confirmed, as stop_all
                    # does) rather than leave the gateway without a poller.
                    w = registry.get(worker_name(gw.id))
                    if w is not None:
                        state = await workers_abort(w)
                        log.warning("old poller for %s did not stop in %.0fs — abort -> %s",
                                    gw.id, DEFER_WAIT_S, state.value)
                    else:
                        old.cancel()
            await asyncio.sleep(0)            # let the reaper free the worker name first
            # The old task is over, so its name is free whatever the reaper has done:
            # a STOPPING record left behind would send start_poller straight back here.
            w = registry.get(worker_name(gw.id))
            if w is not None and w.state is WorkerState.STOPPING and (w._task is None or w._task.done()):
                w.mark_stopped()
                registry.unregister(w.name)
            _deferred.pop(gw.id, None)
            await start_poller(settings, gw)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — a lost restart must at least be loud
            log.exception("deferred poller start for %s failed", gw.id)

    _deferred[gw.id] = asyncio.create_task(_later())
    log.info("poller for %s is still winding down — will start it when it has stopped",
             gw.id)


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
    _stopping[gw_id] = task
    task.add_done_callback(lambda _t, _g=gw_id: _stopping.pop(_g, None)
                           if _stopping.get(_g) is _t else None)
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
    """Shutdown: signal all pollers and await a clean exit (cancel if one overruns).
    Starts waiting on an old poller are dropped, and none begin until it returns (#681)."""
    global _shutting_down
    _shutting_down = True
    try:
        for t in list(_deferred.values()):
            try:
                t.cancel()
            except RuntimeError:          # a start left over from a loop already closed
                pass
        _deferred.clear()
        await _stop_all()
    finally:
        _shutting_down = False


async def _stop_all() -> None:
    ents = list(_pollers.items())
    _pollers.clear()
    for gw_id, (_task, stop) in ents:
        stop.set()
        w = registry.get(worker_name(gw_id))
        if w is not None:
            w.mark_stopping()
    for gw_id, (task, _stop) in ents:
        try:
            await asyncio.wait_for(task, timeout=STOP_GRACE_S)
        except asyncio.CancelledError:
            # A poller already cancelled (an abort, an earlier loop's shutdown) raises
            # CancelledError when awaited; that is its end, not ours (#648). Only a cancel
            # of this shutdown itself goes on up.
            cur = asyncio.current_task()
            if not task.cancelled() or (cur is not None and cur.cancelling()):
                raise
            continue
        except asyncio.TimeoutError:
            # Graceful stop overran, so escalate to abort — and CONFIRM it, because a
            # cancel is a request, not an outcome. If it survives, it is a zombie and
            # saying "aborted" would be a lie that hides a running poller.
            w = registry.get(worker_name(gw_id))
            if w is None:
                task.cancel()
            else:
                state = await workers_abort(w)
                log.warning("poller for %s did not stop in %gs — abort -> %s",
                            gw_id, STOP_GRACE_S, state.value)
            continue
        except Exception:  # noqa: BLE001
            pass
    for gw_id, _ in ents:
        w = registry.get(worker_name(gw_id))
        if w is not None and w.state not in (WorkerState.ABORTED, WorkerState.ZOMBIE):
            w.mark_stopped()
        # A zombie keeps its name forever: it is still executing, so the name must
        # never be reused while it lives.
        if w is None or w.state is not WorkerState.ZOMBIE:
            registry.unregister(worker_name(gw_id))
