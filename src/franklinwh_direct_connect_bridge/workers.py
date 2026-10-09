"""L0 — the component model: named workers, heartbeats, and a supervisor.

See ``docs/RUNTIME_DESIGN.md``. The problem this solves, concretely: background work
was attached three unrelated ways — one asyncio task per gateway, four daemon threads,
and paho's own thread — and none had an owner. ``run_gateway`` could end on an
unhandled exception and nothing retrieved ``task.exception()``, so polling, metrics,
MQTT publishing and all scheduling for that gateway stopped together, permanently, while
``/api/live`` still reported healthy because it deliberately does no gateway I/O.

Three ideas carry the design:

* **Registered, not discovered** (BR-35). Only declared workers appear. Enumerating raw
  asyncio tasks fills the picture with framework plumbing, and then nobody can tell signal
  from noise. If something does background work and is not declared, that is the bug.
* **Liveness is proven, not inferred** (BR-36). A worker beats each cycle. "The task is
  not done" is not liveness — a task can be alive and wedged on a socket read.
* **Degraded is not failed** (BR-38). A poller that cannot reach its aGate is working
  correctly and reporting a device problem. Conflating the two is how "gateway
  unreachable" and "poller crashed" became the same silence.

Phase 0 **registers** existing work rather than rewriting it, so both asyncio tasks and
daemon threads appear here. Converting the threads is phase 1 (decision 1); until then a
thread-backed worker is observable but reports ``restartable=False``.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable

log = logging.getLogger(__name__)


class WorkerState(str, Enum):
    """Lifecycle (design §5.6). Each state exists because it implies a different remedy.

    ``UNRESPONSIVE`` and ``CRASHED`` are deliberately separate: a crashed worker is
    already gone, so restart it; a wedged one still exists, probably blocked on a
    socket, still holds its resources, and must be **cancelled before** anything
    replaces it — restarting without cancelling is how you get a ``ZOMBIE``.
    """

    INIT = "init"                  # constructed; dependencies not resolved
    READY = "ready"                # able to work, not yet working
    RUNNING = "running"            # steady state, beating
    DEGRADED = "degraded"          # doing its job; a dependency is unavailable
    PAUSED = "paused"              # deliberately idle, state retained, resumable
    STOPPING = "stopping"          # winding down — a state with a duration, not an instant
    STOPPED = "stopped"            # stopped cleanly; released what it held
    ABORTED = "aborted"            # stop FORCED — may never have released what it held
    UNRESPONSIVE = "unresponsive"  # task alive, beat stale — cancel, then restart
    CRASHED = "crashed"            # exited with an exception — restart per policy
    ZOMBIE = "zombie"              # superseded but STILL EXECUTING — cancel, never restart


#: States that are terminal for supervision: no restart, no staleness check.
_TERMINAL = frozenset({WorkerState.STOPPED, WorkerState.ABORTED, WorkerState.ZOMBIE})
#: States in which a worker is expected to be beating.
_BEATING = frozenset({WorkerState.RUNNING, WorkerState.DEGRADED})
#: States that mean something went wrong and a remedy is owed.
BROKEN = frozenset({WorkerState.UNRESPONSIVE, WorkerState.CRASHED, WorkerState.ZOMBIE,
                    WorkerState.ABORTED})

#: A stop that never completes is its own failure. `stop_all` already allows 35s before
#: cancelling, so a worker stuck STOPPING past this is escalated rather than waited on.
STOPPING_GRACE_S = 45.0

#: Display order: whatever needs a human first, then stable alphabetical within the band.
#: Sorting "active to top" is arbitrary when everything is running, and a list that
#: reorders between refreshes is one people stop trusting (design §5.4).
_BAND = {
    WorkerState.ZOMBIE: 0, WorkerState.CRASHED: 0, WorkerState.UNRESPONSIVE: 0,
    WorkerState.DEGRADED: 1, WorkerState.STOPPING: 1,
    WorkerState.RUNNING: 2, WorkerState.READY: 2, WorkerState.INIT: 2,
    WorkerState.PAUSED: 3, WorkerState.STOPPED: 3,
    # aborted sits with the broken: it did not shut down cleanly, so something it
    # owned may never have been released, and that is the operator's problem now.
    WorkerState.ABORTED: 0,
}


class RestartClass(str, Enum):
    """Whether restarting this worker is safe, and on what terms (design §5.4)."""

    FREE = "free"
    HANDOFF = "handoff"        # restart, then re-publish state so consumers aren't stale
    GUARDED = "guarded"        # refuse while in-flight work exists, unless it re-adopts


#: A worker that restarts faster than this is not recovering, it is thrashing. It stops
#: and says so instead, because a silent restart loop is the failure mode this whole
#: component model exists to remove (decision 3).
CRASH_LOOP_RESTARTS = 5
CRASH_LOOP_WINDOW_S = 600.0

#: How late a heartbeat may be before the worker is presumed wedged. Generous, because a
#: slow device read is normal and a false "dead" is worse than a late one.
BEAT_GRACE_FACTOR = 4.0
BEAT_GRACE_FLOOR_S = 30.0


@dataclass
class Worker:
    """One unit of background work with exactly one concern."""

    name: str
    concern: str
    cadence_s: float
    scope: str = "global"                      # "global" | "gateway:<id>"
    restart_class: RestartClass = RestartClass.FREE
    kind: str = "task"                         # "task" | "thread"
    factory: Callable[[], Awaitable[Any]] | None = None   # None = not restartable here

    state: WorkerState = WorkerState.INIT
    started_ts: float = field(default_factory=time.time)
    last_beat_ts: float = field(default_factory=time.time)
    restarts: int = 0
    last_error: str = ""
    detail: str = ""
    stopping_since: float | None = None
    _restart_times: list[float] = field(default_factory=list, repr=False)
    _task: asyncio.Task | None = field(default=None, repr=False)

    # ── liveness ──────────────────────────────────────────────────────────────
    def beat(self, *, state: WorkerState | None = None, detail: str = "") -> None:
        """Called by the worker each cycle. The only proof of life that counts."""
        self.last_beat_ts = time.time()
        if state is not None:
            self.state = state
        if detail:
            self.detail = detail

    @property
    def beat_grace_s(self) -> float:
        return max(BEAT_GRACE_FLOOR_S, self.cadence_s * BEAT_GRACE_FACTOR)

    @property
    def beat_age_s(self) -> float:
        return time.time() - self.last_beat_ts

    @property
    def beat_is_stale(self) -> bool:
        """Alive-but-wedged looks exactly like this, and like nothing else.

        Only checked while the worker is expected to beat. An event-driven worker beats
        "alive and waiting" rather than "did work", so an idle watchdog is not stale —
        but one that has stopped beating entirely still is.
        """
        return self.state in _BEATING and self.beat_age_s > self.beat_grace_s

    @property
    def stopping_too_long(self) -> bool:
        """A stop is a state with a duration. One that never completes is invisible
        today, and is exactly what leaves a predecessor running under a reused name."""
        return (self.state is WorkerState.STOPPING
                and self.stopping_since is not None
                and (time.time() - self.stopping_since) > STOPPING_GRACE_S)

    @property
    def is_broken(self) -> bool:
        return self.state in BROKEN

    @property
    def band(self) -> int:
        return _BAND.get(self.state, 2)

    def mark_stopping(self) -> None:
        self.state = WorkerState.STOPPING
        self.stopping_since = time.time()

    def mark_stopped(self) -> None:
        """Wound down cleanly, having released whatever it held."""
        self.state = WorkerState.STOPPED
        self.stopping_since = None

    def mark_aborted(self, reason: str = "") -> None:
        """Stop was FORCED. Distinct from stopped on purpose: a cancelled worker may
        never have released a force, closed a session or finished a write, and that
        difference is the only evidence a cleanup was skipped."""
        self.state = WorkerState.ABORTED
        self.stopping_since = None
        self.last_error = reason or "cancelled before it wound down"

    @property
    def restartable(self) -> bool:
        """Can this be restarted *at all*? Whether it is safe *right now* is
        ``restart_block``, because the two questions have different answers."""
        return self.factory is not None and self.kind == "task"

    def restart_block(self, *, guard: Callable[[], str] | None = None) -> str:
        """Empty string = safe to restart now; otherwise the reason it is not.

        The GUARDED class is the point: restarting the dispatch watchdog while a force
        is in flight removes the only thing that ends it, since this firmware's hardware
        revert timer is cosmetic. Such a restart must re-adopt the force, not start clean.
        """
        if not self.restartable:
            return ("not restartable: thread-backed (convert to a worker in phase 1)"
                    if self.kind == "thread" else "not restartable: no factory registered")
        if self.state is WorkerState.STOPPING:
            return "winding down — wait for it to finish"
        if self.in_crash_loop():
            return (f"crash loop: {CRASH_LOOP_RESTARTS} restarts within "
                    f"{CRASH_LOOP_WINDOW_S / 60:.0f} min — fix the cause, then restart")
        if self.restart_class is RestartClass.GUARDED and guard is not None:
            return guard()
        return ""

    def in_crash_loop(self, now: float | None = None) -> bool:
        now = now if now is not None else time.time()
        recent = [t for t in self._restart_times if now - t <= CRASH_LOOP_WINDOW_S]
        return len(recent) >= CRASH_LOOP_RESTARTS

    def note_restart(self, now: float | None = None) -> None:
        now = now if now is not None else time.time()
        self._restart_times = [t for t in self._restart_times
                               if now - t <= CRASH_LOOP_WINDOW_S] + [now]
        self.restarts += 1

    def as_dict(self) -> dict:
        return {
            "name": self.name, "concern": self.concern, "scope": self.scope,
            "kind": self.kind, "state": self.state.value,
            "restart_class": self.restart_class.value, "restartable": self.restartable,
            "cadence_s": self.cadence_s,
            "uptime_s": round(time.time() - self.started_ts, 1),
            "last_beat_s": round(self.beat_age_s, 1),
            "beat_stale": self.beat_is_stale,
            "restarts": self.restarts, "last_error": self.last_error,
            "detail": self.detail, "broken": self.is_broken, "band": self.band,
            "family": self.name.split(":", 1)[0],
        }


class Registry:
    """Every worker in the process. Thread-safe: daemon threads beat into it too."""

    def __init__(self) -> None:
        self._workers: dict[str, Worker] = {}
        self._lock = threading.RLock()

    def name_in_use(self, name: str) -> Worker | None:
        """A name is in use while any predecessor is still winding down or wedged.

        This is the zombie fix (BR-40). Previously `is_running()` consulted a dict of
        tasks that `stop_poller` had already popped, so a quick disable→enable started a
        second poller while the first was still mid-cycle — both polling, both writing
        metrics, both publishing MQTT for the same node, and the older one invisible
        because it had been deregistered. The registry, not a task dict, decides.
        """
        with self._lock:
            w = self._workers.get(name)
            if w is None:
                return None
            if w.state in (WorkerState.STOPPING, WorkerState.UNRESPONSIVE, WorkerState.ZOMBIE):
                return w
            if w._task is not None and not w._task.done():
                return w
            return None

    def register(self, worker: Worker) -> Worker:
        with self._lock:
            existing = self._workers.get(worker.name)
            if existing is not None and existing._task is not None and not existing._task.done():
                # Replacing a live worker would orphan it: still executing, no longer
                # listed, still producing side effects. Name it for what it is.
                existing.state = WorkerState.ZOMBIE
                existing.last_error = "superseded while still running"
                log.error("worker %s superseded while still running — ZOMBIE", existing.name)
            if existing is not None:
                # Re-registering after a restart keeps the history that makes a crash
                # loop visible; dropping it would reset the evidence each time.
                worker.restarts = existing.restarts
                worker._restart_times = list(existing._restart_times)
            self._workers[worker.name] = worker
            return worker

    def unregister(self, name: str) -> None:
        with self._lock:
            self._workers.pop(name, None)

    def get(self, name: str) -> Worker | None:
        with self._lock:
            return self._workers.get(name)

    def all(self) -> list[Worker]:
        with self._lock:
            return sorted(self._workers.values(),
                          key=lambda w: (w.band, w.name.split(':', 1)[0], w.name))

    def beat(self, name: str, *, state: WorkerState | None = None, detail: str = "") -> None:
        """Beat by name, so a worker need not hold a reference to its own record."""
        w = self.get(name)
        if w is not None:
            w.beat(state=state, detail=detail)

    def snapshot(self) -> dict:
        ws = self.all()
        unhealthy = [w for w in ws if w.is_broken or w.beat_is_stale]
        return {
            "ok": not unhealthy,
            "counts": {s.value: sum(1 for w in ws if w.state is s) for s in WorkerState},
            "stale": [w.name for w in ws if w.beat_is_stale],
            "broken": [w.name for w in ws if w.is_broken],
            "workers": [w.as_dict() for w in ws],
        }


#: Process-wide registry. One per process by design; passing it around everywhere buys
#: nothing when the thing it models is the process itself.
registry = Registry()


async def supervise(reg: Registry, *, stop: asyncio.Event, interval_s: float = 5.0,
                    on_transition: Callable[[Worker, str], None] | None = None) -> None:
    """The supervisor loop (BR-37). Itself a worker — register it like any other.

    Each pass: retrieve exceptions from finished tasks so nothing exits unreported,
    mark wedged workers failed even though their task looks alive, and restart per
    policy until the crash-loop ceiling, after which the worker stays FAILED and says so.
    """
    while not stop.is_set():
        try:
            _supervise_once(reg, on_transition=on_transition)
        except Exception:  # noqa: BLE001 — the supervisor must outlive its subjects
            log.exception("supervisor pass failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval_s)
        except asyncio.TimeoutError:
            pass


def _supervise_once(reg: Registry, *, on_transition=None) -> list[Worker]:
    """One pass. Pure enough to test without a loop; returns workers needing a remedy."""
    needs: list[Worker] = []
    for w in reg.all():
        if w.state in _TERMINAL:
            continue

        task = w._task

        # A stop that completed: finish the deregistration the stop only began. Doing
        # this here — rather than at the moment stop was *requested* — is what stops a
        # replacement starting alongside a predecessor that is still running.
        if w.state is WorkerState.STOPPING:
            if task is None or task.done():
                w.mark_stopped()
                reg.unregister(w.name)
            elif w.stopping_too_long:
                _transition(w, WorkerState.UNRESPONSIVE,
                            f"still stopping after {STOPPING_GRACE_S:.0f}s", on_transition)
                needs.append(w)
            continue

        if task is not None and task.done():
            # Never exit unreported: retrieve the exception, or Python merely logs
            # "Task exception was never retrieved" into the void — which is how
            # run_gateway could die silently.
            err = ""
            if not task.cancelled():
                exc = task.exception()
                if exc is not None:
                    err = f"{type(exc).__name__}: {exc}"
            _transition(w, WorkerState.CRASHED, err or "exited without error", on_transition)
            needs.append(w)
            continue

        if w.beat_is_stale:
            # Alive but wedged. NOT crashed: the task still exists and holds its
            # resources, so the remedy is cancel-then-restart, not restart.
            _transition(w, WorkerState.UNRESPONSIVE,
                        f"no heartbeat for {w.beat_age_s:.0f}s "
                        f"(cadence {w.cadence_s:.0f}s)", on_transition)
            needs.append(w)
    return needs


def _transition(w: Worker, state: WorkerState, reason: str, on_transition) -> None:
    if w.state is state:
        return
    w.state = state
    w.last_error = reason
    log.error("worker %s -> %s: %s", w.name, state.value, reason)
    if on_transition is not None:
        try:
            on_transition(w, reason)
        except Exception:  # noqa: BLE001 — observing must never break supervising
            log.debug("worker transition hook failed for %s", w.name, exc_info=True)
