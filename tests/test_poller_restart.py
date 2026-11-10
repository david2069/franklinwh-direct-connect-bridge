"""#82 — editing a gateway must not leave it without a poller.

Editing a gateway (PATCH, e.g. turning Publish to HA on) stops its poller and starts it
again at once. The old poller only checks its stop event at the end of a cycle, so it was
still STOPPING when the start came; start_poller refused ("still winding down — not
starting a second one") and nothing retried. The gateway stayed dead, its HA entities
"unavailable", until the add-on restarted.
"""
import asyncio

import franklinwh_direct_connect_bridge.supervisor as sup
from franklinwh_direct_connect_bridge.state import GatewayState


def _fake_run(stop_delay: float, runs: list, live: dict):
    async def fake_run(settings, gw, stop):
        live["n"] += 1
        live["max"] = max(live["max"], live["n"])
        runs.append(gw.id)
        try:
            await stop.wait()
            await asyncio.sleep(stop_delay)   # a cycle mid-read, as on a real aGate
        finally:
            live["n"] -= 1
    return fake_run


def _run(scenario, monkeypatch, stop_delay=0.2):
    runs, live = [], {"n": 0, "max": 0}
    monkeypatch.setattr(sup, "run_gateway", _fake_run(stop_delay, runs, live))
    asyncio.run(scenario())
    return runs, live


def test_a_restart_while_stopping_starts_once_the_old_poller_is_gone(monkeypatch):
    async def scenario():
        gw = GatewayState(id="r1", label="R1")
        await sup.start_poller(None, gw)
        await sup.stop_poller("r1")              # what _reconcile_gateway does...
        await sup.start_poller(None, gw)         # ...followed at once by this
        for _ in range(100):                     # up to 2 s
            await asyncio.sleep(0.02)
            ent = sup._pollers.get("r1")
            if ent and not ent[0].done() and "r1" not in sup._deferred:
                break
        ent = sup._pollers.get("r1")
        assert ent is not None and not ent[0].done(), "no poller after the edit"
        await sup.stop_poller("r1")
        await asyncio.sleep(0.4)

    runs, live = _run(scenario, monkeypatch)
    assert runs == ["r1", "r1"]                  # started again, exactly once
    assert live["max"] == 1                      # never two pollers at the same time


def test_repeated_edits_do_not_queue_several_starts(monkeypatch):
    async def scenario():
        gw = GatewayState(id="r2", label="R2")
        await sup.start_poller(None, gw)
        await sup.stop_poller("r2")
        for _ in range(3):                       # three quick edits
            await sup.start_poller(None, gw)
        await asyncio.sleep(0.6)
        await sup.stop_poller("r2")
        await asyncio.sleep(0.4)

    runs, live = _run(scenario, monkeypatch)
    assert runs == ["r2", "r2"] and live["max"] == 1


def test_an_old_poller_that_never_stops_is_aborted_not_waited_on_forever(monkeypatch):
    monkeypatch.setattr(sup, "DEFER_WAIT_S", 0.2)

    async def scenario():
        gw = GatewayState(id="r3", label="R3")
        await sup.start_poller(None, gw)
        await sup.stop_poller("r3")
        await sup.start_poller(None, gw)
        await asyncio.sleep(1.5)
        ent = sup._pollers.get("r3")
        assert ent is not None and not ent[0].done(), "stuck predecessor blocked the restart"
        sup._pollers.pop("r3")[0].cancel()
        await asyncio.sleep(0.05)

    _run(scenario, monkeypatch, stop_delay=60)   # the old one would take a minute
