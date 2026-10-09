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
    assert [w.name for w in reg.all()] == ["a", "b"]   # band, then family, then name


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
def test_a_task_that_raised_is_marked_crashed_with_its_exception(reg):
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
    assert w.state is W.WorkerState.CRASHED
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


def test_stale_heartbeat_marks_unresponsive_not_crashed(reg):
    w = reg.register(_w("thready", kind="thread", cadence=1.0))
    w.beat(state=W.WorkerState.RUNNING)
    w.last_beat_ts = time.time() - 10_000
    needs = W._supervise_once(reg)
    assert w.state is W.WorkerState.UNRESPONSIVE, (
        "wedged is not crashed: the task still exists and must be cancelled first")
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
    assert w.state is W.WorkerState.UNRESPONSIVE


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
def test_snapshot_is_ok_only_when_nothing_is_broken_or_stale(reg):
    a = reg.register(_w("a")); a.beat(state=W.WorkerState.RUNNING)
    assert reg.snapshot()["ok"] is True
    b = reg.register(_w("b")); b.state = W.WorkerState.CRASHED
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
    W.registry.register(_w("broken-on-purpose")).state = W.WorkerState.CRASHED
    try:
        assert client.get("/api/health/workers").json()["ok"] is False
        assert client.get("/api/live").status_code == 200
    finally:
        W.registry.unregister("broken-on-purpose")


# ── 0b · lifecycle distinctions (BR-39) ───────────────────────────────────────
def test_stopping_is_a_state_with_a_duration(reg):
    w = reg.register(_w("p")); w.mark_stopping()
    assert w.state is W.WorkerState.STOPPING
    assert not w.stopping_too_long
    w.stopping_since = time.time() - (W.STOPPING_GRACE_S + 5)
    assert w.stopping_too_long, "a stop that never completes is its own failure"


def test_a_stop_that_hangs_becomes_unresponsive_not_silently_ignored(reg):
    # Only a stop with a task STILL RUNNING can hang; with no task the stop is
    # trivially complete, which the next test covers.
    async def main():
        w = reg.register(_w("p"))
        w._task = asyncio.create_task(asyncio.sleep(5))
        w.mark_stopping()
        w.stopping_since = time.time() - (W.STOPPING_GRACE_S + 5)
        needs = W._supervise_once(reg)
        w._task.cancel()
        return w.state, needs

    state, needs = asyncio.run(main())
    assert state is W.WorkerState.UNRESPONSIVE
    assert [n.name for n in needs] == ["p"]


def test_paused_is_not_stopped_and_is_not_expected_to_beat(reg):
    w = reg.register(_w("p")); w.state = W.WorkerState.PAUSED
    w.last_beat_ts = time.time() - 10_000
    assert not w.beat_is_stale
    assert W._supervise_once(reg) == []


def test_an_event_driven_worker_idling_is_not_stale(reg):
    # It beats "alive and waiting", not "did work" — otherwise every idle watchdog
    # reads as dead.
    w = reg.register(_w("dispatch-watchdog", cadence=30.0))
    w.beat(state=W.WorkerState.RUNNING)
    assert not w.beat_is_stale


# ── 0b · the zombie fix (BR-40) ───────────────────────────────────────────────
def test_a_name_is_in_use_while_its_predecessor_winds_down(reg):
    w = reg.register(_w("poller:gw1")); w.mark_stopping()
    assert reg.name_in_use("poller:gw1") is w, (
        "this is the whole fix: a stop that has been requested is not a stop that finished")


def test_a_name_is_free_once_the_stop_completes(reg):
    w = reg.register(_w("poller:gw1")); w.mark_stopping()
    W._supervise_once(reg)                      # no task -> stop is complete
    assert reg.name_in_use("poller:gw1") is None
    assert reg.get("poller:gw1") is None, "deregistered only once work has ended"


def test_replacing_a_live_worker_marks_the_old_one_a_zombie(reg):
    async def main():
        old = reg.register(_w("poller:gw1"))
        old._task = asyncio.create_task(asyncio.sleep(5))
        old.beat(state=W.WorkerState.RUNNING)
        reg.register(_w("poller:gw1"))          # a second start under the same name
        state = old.state
        old._task.cancel()
        return state

    assert asyncio.run(main()) is W.WorkerState.ZOMBIE, (
        "still executing, no longer listed, still producing side effects")


def test_zombies_are_terminal_and_never_restarted(reg):
    w = reg.register(_w("z")); w.state = W.WorkerState.ZOMBIE
    assert W._supervise_once(reg) == []
    assert w.restart_block() != ""


# ── 0b · restart safety (design §5.4) ─────────────────────────────────────────
def test_restart_is_blocked_while_winding_down(reg):
    w = reg.register(_w("p", factory=lambda: None)); w.mark_stopping()
    assert "winding down" in w.restart_block()


def test_restart_is_blocked_during_a_crash_loop(reg):
    w = reg.register(_w("p", factory=lambda: None))
    for _ in range(W.CRASH_LOOP_RESTARTS):
        w.note_restart()
    assert "crash loop" in w.restart_block()


def test_guarded_restart_consults_the_guard(reg):
    w = reg.register(_w("dispatch-watchdog", factory=lambda: None,
                        restart_class=W.RestartClass.GUARDED))
    assert w.restart_block(guard=lambda: "") == ""
    assert "force active" in w.restart_block(guard=lambda: "force active")


def test_thread_backed_workers_say_why_they_cannot_restart(reg):
    w = reg.register(_w("vpp-monitor", kind="thread"))
    assert "thread-backed" in w.restart_block()


# ── 0b · display ordering (design §5.4) ───────────────────────────────────────
def test_broken_workers_sort_above_healthy_ones(reg):
    for n, st in (("zzz-ok", W.WorkerState.RUNNING), ("aaa-crashed", W.WorkerState.CRASHED),
                  ("mmm-degraded", W.WorkerState.DEGRADED), ("bbb-stopped", W.WorkerState.STOPPED)):
        reg.register(_w(n)).state = st
    assert [w.name for w in reg.all()] == [
        "aaa-crashed", "mmm-degraded", "zzz-ok", "bbb-stopped"]


def test_ordering_is_stable_alphabetical_within_a_band(reg):
    for n in ("poller:c", "poller:a", "poller:b"):
        reg.register(_w(n)).state = W.WorkerState.RUNNING
    assert [w.name for w in reg.all()] == ["poller:a", "poller:b", "poller:c"], (
        "a list that reorders between refreshes is one people stop trusting")


# ── 0b · the restart endpoint ─────────────────────────────────────────────────
def test_restart_unknown_worker_is_404():
    assert _client().post("/api/health/workers/nope/restart").status_code in (403, 404)


def test_restart_refuses_a_thread_backed_worker_with_a_reason():
    # Register explicitly: a plain TestClient does not run the lifespan, so nothing is
    # registered by startup here.
    W.registry.register(_w("vpp-monitor-test", kind="thread"))
    try:
        r = _client().post("/api/health/workers/vpp-monitor-test/restart")
        # 403 when the write gate is shut, else 409 with the reason — never a silent no-op.
        assert r.status_code in (403, 409)
        if r.status_code == 409:
            assert "thread-backed" in r.json()["detail"]
    finally:
        W.registry.unregister("vpp-monitor-test")


# ── v1.1 · aborted is not stopped (design §5.6) ───────────────────────────────
def test_aborted_is_distinct_from_stopped(reg):
    a = reg.register(_w("a")); a.mark_stopped()
    b = reg.register(_w("b")); b.mark_aborted()
    assert a.state is W.WorkerState.STOPPED
    assert b.state is W.WorkerState.ABORTED
    assert "cancelled" in b.last_error


def test_aborted_counts_as_broken_so_it_is_not_mistaken_for_a_clean_stop(reg):
    w = reg.register(_w("a")); w.mark_aborted("did not wind down")
    assert w.is_broken, "a forced stop may have skipped a cleanup — say so"
    assert reg.snapshot()["ok"] is False
    assert "a" in reg.snapshot()["broken"]


def test_a_clean_stop_is_not_broken(reg):
    w = reg.register(_w("a")); w.mark_stopped()
    assert not w.is_broken and reg.snapshot()["ok"] is True


def test_aborted_sorts_with_the_things_needing_attention(reg):
    reg.register(_w("zzz-running")).state = W.WorkerState.RUNNING
    reg.register(_w("aaa-stopped")).mark_stopped()
    reg.register(_w("mmm-aborted")).mark_aborted()
    assert [w.name for w in reg.all()][0] == "mmm-aborted"


def test_aborted_is_terminal_and_not_supervised(reg):
    w = reg.register(_w("a")); w.mark_aborted()
    assert W._supervise_once(reg) == []
