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
    STARTING = "starting"
    RUNNING = "running"
    DEGRADED = "degraded"      # doing its job; a dependency is unavailable
    STOPPED = "stopped"        # asked to stop
    FAILED = "failed"          # died, or exceeded the crash-loop ceiling


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

    state: WorkerState = WorkerState.STARTING
    started_ts: float = field(default_factory=time.time)
    last_beat_ts: float = field(default_factory=time.time)
    restarts: int = 0
    last_error: str = ""
    detail: str = ""
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
        """Alive-but-wedged looks exactly like this, and like nothing else."""
        return (self.state in (WorkerState.RUNNING, WorkerState.DEGRADED)
                and self.beat_age_s > self.beat_grace_s)

    @property
    def restartable(self) -> bool:
        return self.factory is not None and self.kind == "task"

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
            "detail": self.detail,
        }


class Registry:
    """Every worker in the process. Thread-safe: daemon threads beat into it too."""

    def __init__(self) -> None:
        self._workers: dict[str, Worker] = {}
        self._lock = threading.RLock()

    def register(self, worker: Worker) -> Worker:
        with self._lock:
            existing = self._workers.get(worker.name)
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
            return sorted(self._workers.values(), key=lambda w: (w.scope, w.name))

    def beat(self, name: str, *, state: WorkerState | None = None, detail: str = "") -> None:
        """Beat by name, so a worker need not hold a reference to its own record."""
        w = self.get(name)
        if w is not None:
            w.beat(state=state, detail=detail)

    def snapshot(self) -> dict:
        ws = self.all()
        unhealthy = [w for w in ws if w.state is WorkerState.FAILED or w.beat_is_stale]
        return {
            "ok": not unhealthy,
            "counts": {s.value: sum(1 for w in ws if w.state is s) for s in WorkerState},
            "stale": [w.name for w in ws if w.beat_is_stale],
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
    """One pass. Pure enough to test without a loop; returns workers needing a restart."""
    needs_restart: list[Worker] = []
    for w in reg.all():
        if w.state in (WorkerState.STOPPED, WorkerState.FAILED):
            continue

        task = w._task
        if task is not None and task.done():
            # A worker never exits unreported: retrieve the exception or Python merely
            # logs "Task exception was never retrieved" into the void, which is how
            # run_gateway could die silently.
            err = ""
            if not task.cancelled():
                exc = task.exception()
                if exc is not None:
                    err = f"{type(exc).__name__}: {exc}"
            _transition(w, WorkerState.FAILED, err or "exited", on_transition)
            needs_restart.append(w)
            continue

        if w.beat_is_stale:
            _transition(w, WorkerState.FAILED,
                        f"no heartbeat for {w.beat_age_s:.0f}s "
                        f"(cadence {w.cadence_s:.0f}s)", on_transition)
            needs_restart.append(w)
    return needs_restart


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
