"""#648: the full suite's "flaky" gateway-identity test failed in the app's shutdown, not in
its own check. ``supervisor.stop_all`` let a poller's CancelledError escape (it isn't an
Exception), cutting the shutdown short, and on an overrun it aborted the worker named by a
stale loop variable: the last gateway's, not the slow one's."""
import asyncio

from franklinwh_direct_connect_bridge import supervisor, workers


def _register(gw_id, task):
    w = workers.registry.register(workers.Worker(
        name=supervisor.worker_name(gw_id), concern="poll", cadence_s=30.0,
        restart_class=workers.RestartClass.FREE, kind="task"))
    w._task = task
    return w


def test_a_poller_already_cancelled_does_not_stop_the_shutdown():
    async def go():
        async def poll(stop):
            await stop.wait()
        dead = asyncio.create_task(asyncio.sleep(60))
        dead.cancel()
        live_stop = asyncio.Event()
        live = asyncio.create_task(poll(live_stop))
        supervisor._pollers.update({"gwA": (dead, asyncio.Event()), "gwB": (live, live_stop)})
        await asyncio.sleep(0)
        await supervisor.stop_all()                 # must not raise
        return live.done()
    assert asyncio.run(go()) is True


def test_an_overrun_aborts_the_slow_pollers_worker_not_another(monkeypatch):
    monkeypatch.setattr(supervisor, "STOP_GRACE_S", 0.2)
    aborted = []

    async def fake_abort(w):
        aborted.append(w.name)
        w._task.cancel()
        return workers.WorkerState.ABORTED
    monkeypatch.setattr(supervisor, "workers_abort", fake_abort)

    async def go():
        async def slow(stop):
            await asyncio.sleep(60)                 # ignores stop
        async def quick(stop):
            await stop.wait()
        s1, s2 = asyncio.Event(), asyncio.Event()
        t1, t2 = asyncio.create_task(slow(s1)), asyncio.create_task(quick(s2))
        _register("slowgw", t1), _register("quickgw", t2)
        supervisor._pollers.update({"slowgw": (t1, s1), "quickgw": (t2, s2)})
        await supervisor.stop_all()
    try:
        asyncio.run(go())
    finally:
        for n in ("slowgw", "quickgw"):
            workers.registry.unregister(supervisor.worker_name(n))
    assert aborted == [supervisor.worker_name("slowgw")]
