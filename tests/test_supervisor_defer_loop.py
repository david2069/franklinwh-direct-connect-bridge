"""#681: a gateway edit leaves a deferred poller start waiting for the old poller. If the
bridge then shuts down, stop_all marked the pollers STOPPING without listing them as
winding down, so the deferred start found nothing to wait on, saw the name still in use,
and deferred again at once: 409,682 log lines in 30 s while shutdown waited on a slow
poller. A deferred start must wait (never spin), and no poller starts during shutdown."""
import asyncio
from types import SimpleNamespace

import pytest

from franklinwh_direct_connect_bridge import supervisor as sv, workers
from franklinwh_direct_connect_bridge.state import GatewayState


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for d in (sv._pollers, sv._stopping, sv._deferred):
        d.clear()
    monkeypatch.setattr(sv, "_shutting_down", False, raising=False)
    yield
    for n in ("g1", "g2"):
        workers.registry.unregister(sv.worker_name(n))


def _run(scenario, monkeypatch, hold_s=1.0):
    defers, started = [], []
    real_defer = sv._defer_start
    monkeypatch.setattr(sv, "_defer_start", lambda s, gw: defers.append(gw.id) or real_defer(s, gw))
    monkeypatch.setattr(sv, "DEFER_WAIT_S", 5.0)
    monkeypatch.setattr(sv, "STOP_GRACE_S", 0.5)

    async def slow_poller(settings, gw, stop):     # a cycle stuck in a read, ignoring stop
        started.append(gw.id)
        await asyncio.sleep(hold_s)
    monkeypatch.setattr(sv, "run_gateway", slow_poller)

    async def go():
        s = SimpleNamespace(poll_interval=30)
        gws = [GatewayState(id=g, configured_host="h") for g in ("g1", "g2")]
        await scenario(s, gws)
        for _ in range(20):
            await asyncio.sleep(0.05)
        for t in list(sv._deferred.values()):
            t.cancel()
    asyncio.run(go())
    return defers, started


def test_shutdown_after_an_edit_does_not_spin_or_start_a_poller(monkeypatch):
    async def edit_then_shutdown(s, gws):
        for gw in gws:
            await sv.start_poller(s, gw)
        await asyncio.sleep(0.05)
        for gw in gws:                         # PATCH: stop, then start (deferred)
            await sv.stop_poller(gw.id)
            await sv.start_poller(s, gw)
        await sv.stop_all()                    # the bridge shuts down
    defers, started = _run(edit_then_shutdown, monkeypatch)
    assert len(defers) == 2                    # one per edit, never again
    assert started == ["g1", "g2"]             # nothing started after the shutdown


def test_a_deferred_start_waits_for_a_stopping_name_with_no_old_task(monkeypatch):
    """The name is still STOPPING but nothing is listed as winding down: wait on the
    worker's own task, then start once."""
    async def scenario(s, gws):
        gw = gws[0]
        await sv.start_poller(s, gw)
        await asyncio.sleep(0.05)
        task, stop = sv._pollers.pop(gw.id)    # stopped the way stop_all does
        stop.set()
        workers.registry.get(sv.worker_name(gw.id)).mark_stopping()
        await sv.start_poller(s, gw)
    defers, started = _run(scenario, monkeypatch, hold_s=0.3)
    assert len(defers) == 1
    assert started == ["g1", "g1"]             # the old one, then one new one


def test_a_start_left_from_a_closed_loop_does_not_block_later_starts(monkeypatch):
    """A deferred start whose event loop has closed (a previous app run) must not leave
    the bridge refusing every start after the next shutdown."""
    async def leave_one():
        f = asyncio.get_running_loop().create_future()
        f.add_done_callback(lambda _f: None)   # cancelling it schedules on its (closed) loop
        sv._deferred["g9"] = f
    asyncio.run(leave_one())                   # its loop is closed now
    asyncio.run(sv.stop_all())
    assert sv._shutting_down is False and not sv._deferred
