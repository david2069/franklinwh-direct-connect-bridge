"""L0 worker model: registration, heartbeat liveness, supervision, crash-loop ceiling.

The behaviours worth protecting are the ones whose absence caused the silence this
design exists to remove: a task that exits without its exception being retrieved, a
worker that is alive but wedged, and a restart loop nobody can see.
"""
import asyncio
import time

import pytest

from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import app as app_module
from franklinwh_direct_connect_bridge import workers as W


def _client():
    return TestClient(app_module.create_app())


def _w(name="poller:gw1", cadence=5.0, **kw):
    return W.Worker(name=name, concern="test", cadence_s=cadence, **kw)


@pytest.fixture
def reg():
    return W.Registry()


# ── registration (BR-35) ──────────────────────────────────────────────────────
def test_only_registered_workers_appear(reg):
    reg.register(_w("a"))
    reg.register(_w("b", scope="gateway:x"))
    assert [w.name for w in reg.all()] == ["b", "a"]   # sorted by scope then name


def test_re_registering_keeps_restart_history(reg):
    w = reg.register(_w("a"))
    w.note_restart(); w.note_restart()
    fresh = reg.register(_w("a"))
    assert fresh.restarts == 2, "a crash loop must stay visible across re-registration"


# ── liveness is proven, not inferred (BR-36) ──────────────────────────────────
def test_a_fresh_worker_is_not_stale(reg):
    w = reg.register(_w(cadence=1.0))
    w.beat(state=W.WorkerState.RUNNING)
    assert not w.beat_is_stale


def test_a_wedged_worker_is_stale_even_though_its_task_is_alive(reg):
    w = reg.register(_w(cadence=1.0))
    w.beat(state=W.WorkerState.RUNNING)
    w.last_beat_ts = time.time() - 10_000
    assert w.beat_is_stale, "alive-but-wedged is exactly what a heartbeat is for"


def test_grace_scales_with_cadence_but_has_a_floor():
    assert _w(cadence=1.0).beat_grace_s == W.BEAT_GRACE_FLOOR_S
    assert _w(cadence=60.0).beat_grace_s == 240.0


def test_stopped_workers_are_never_stale(reg):
    w = reg.register(_w())
    w.state = W.WorkerState.STOPPED
    w.last_beat_ts = time.time() - 10_000
    assert not w.beat_is_stale, "a stopped worker is not a dead one"


def test_degraded_still_beats_and_is_not_failed(reg):
    # A poller that cannot reach its aGate is working correctly (BR-38).
    w = reg.register(_w())
    w.beat(state=W.WorkerState.DEGRADED, detail="aGate unreachable")
    assert w.state is W.WorkerState.DEGRADED
    assert not w.beat_is_stale
    assert w.as_dict()["detail"] == "aGate unreachable"


# ── supervision (BR-37) ───────────────────────────────────────────────────────
def test_a_task_that_raised_is_marked_failed_with_its_exception(reg):
    async def main():
        w = reg.register(_w("boom"))
        w.beat(state=W.WorkerState.RUNNING)

        async def explode():
            raise RuntimeError("poll loop died")

        w._task = asyncio.create_task(explode())
        await asyncio.sleep(0.01)
        return W._supervise_once(reg)

    needs = asyncio.run(main())
    w = reg.get("boom")
    assert w.state is W.WorkerState.FAILED
    assert "RuntimeError: poll loop died" in w.last_error
    assert needs == [w], "a dead worker must be offered for restart"


def test_a_cancelled_task_is_not_reported_as_an_error(reg):
    async def main():
        w = reg.register(_w("cancelled"))
        w.beat(state=W.WorkerState.RUNNING)
        t = asyncio.create_task(asyncio.sleep(10))
        w._task = t
        t.cancel()
        await asyncio.sleep(0.01)
        W._supervise_once(reg)

    asyncio.run(main())
    assert "Cancelled" not in reg.get("cancelled").last_error


def test_stale_heartbeat_fails_the_worker_without_any_task(reg):
    w = reg.register(_w("thready", kind="thread", cadence=1.0))
    w.beat(state=W.WorkerState.RUNNING)
    w.last_beat_ts = time.time() - 10_000
    needs = W._supervise_once(reg)
    assert w.state is W.WorkerState.FAILED
    assert "no heartbeat" in w.last_error
    assert needs == [w]


def test_supervision_is_idempotent_and_does_not_re_notify(reg):
    seen = []
    w = reg.register(_w("x", cadence=1.0))
    w.beat(state=W.WorkerState.RUNNING)
    w.last_beat_ts = time.time() - 10_000
    W._supervise_once(reg, on_transition=lambda worker, why: seen.append(why))
    W._supervise_once(reg, on_transition=lambda worker, why: seen.append(why))
    assert len(seen) == 1, "transition hooks fire on transition, not every pass"


def test_a_broken_transition_hook_never_breaks_supervision(reg):
    w = reg.register(_w("x", cadence=1.0))
    w.beat(state=W.WorkerState.RUNNING)
    w.last_beat_ts = time.time() - 10_000

    def boom(worker, why):
        raise RuntimeError("notifier down")

    W._supervise_once(reg, on_transition=boom)
    assert w.state is W.WorkerState.FAILED


# ── crash-loop ceiling (decision 3) ───────────────────────────────────────────
def test_crash_loop_is_detected_at_the_ceiling(reg):
    w = reg.register(_w())
    for _ in range(W.CRASH_LOOP_RESTARTS - 1):
        w.note_restart()
    assert not w.in_crash_loop()
    w.note_restart()
    assert w.in_crash_loop(), "thrashing must stop and say so, not keep retrying quietly"


def test_restarts_outside_the_window_do_not_count(reg):
    w = reg.register(_w())
    old = time.time() - (W.CRASH_LOOP_WINDOW_S + 60)
    w._restart_times = [old] * 10
    assert not w.in_crash_loop()


# ── restart safety (design §5.4) ──────────────────────────────────────────────
def test_thread_backed_workers_are_observable_but_not_restartable(reg):
    w = reg.register(_w("vpp-monitor", kind="thread"))
    assert w.as_dict()["restartable"] is False


def test_guarded_class_is_carried_through_to_the_api(reg):
    w = reg.register(_w("dispatch-watchdog",
                        restart_class=W.RestartClass.GUARDED, kind="thread"))
    assert w.as_dict()["restart_class"] == "guarded"


# ── the surface (BR-38) ───────────────────────────────────────────────────────
def test_snapshot_is_ok_only_when_nothing_is_failed_or_stale(reg):
    a = reg.register(_w("a")); a.beat(state=W.WorkerState.RUNNING)
    assert reg.snapshot()["ok"] is True
    b = reg.register(_w("b")); b.state = W.WorkerState.FAILED
    assert reg.snapshot()["ok"] is False


def test_snapshot_names_stale_workers(reg):
    w = reg.register(_w("wedged", cadence=1.0)); w.beat(state=W.WorkerState.RUNNING)
    w.last_beat_ts = time.time() - 10_000
    assert reg.snapshot()["stale"] == ["wedged"]


def test_supervise_loop_stops_promptly_when_asked():
    async def main():
        reg2 = W.Registry()
        stop = asyncio.Event()
        t = asyncio.create_task(W.supervise(reg2, stop=stop, interval_s=30))
        await asyncio.sleep(0.01)
        stop.set()
        await asyncio.wait_for(t, timeout=2.0)   # must not wait out the interval

    asyncio.run(main())


# ── the HTTP surface ──────────────────────────────────────────────────────────
def test_health_workers_endpoint_reports_declared_workers():
    client = _client()
    r = client.get("/api/health/workers")
    assert r.status_code == 200
    body = r.json()
    assert set(body) >= {"ok", "counts", "stale", "workers"}
    for w in body["workers"]:
        # Every row must answer "can I restart this, and is it safe?" without
        # the reader going to the source.
        assert set(w) >= {"name", "concern", "scope", "state",
                          "restart_class", "restartable", "last_beat_s"}
        assert w["restart_class"] in ("free", "handoff", "guarded")


def test_workers_endpoint_does_not_drive_api_live():
    client = _client()
    # Decision 4: a failed worker must not fail the container, or a crash loop at
    # container level destroys the evidence needed to find out why.
    W.registry.register(_w("broken-on-purpose")).state = W.WorkerState.FAILED
    try:
        assert client.get("/api/health/workers").json()["ok"] is False
        assert client.get("/api/live").status_code == 200
    finally:
        W.registry.unregister("broken-on-purpose")
