"""#284: a failed poll does not refresh the snapshot, so the scheduler stops evaluating a
dead gateway (and never blocks its tick on that gateway's clock read)."""

import asyncio

from franklinwh_direct_connect_bridge import config, poller, scheduler_worker as SW
from franklinwh_direct_connect_bridge.state import GatewayState


class _Pub:
    def __init__(self, *a, **k): pass
    def start(self): pass
    def stop(self): pass
    def is_connected(self): return False
    def publish_state(self, st): pass
    def publish_availability(self, online): pass
    def publish_alerts(self, payload): pass


def _poll_once(monkeypatch, summ):
    s = config.get_settings()
    monkeypatch.setattr(s, "mqtt_enabled", False)
    monkeypatch.setattr(s, "poll_interval", 1)
    monkeypatch.setattr(poller, "MqttPublisher", _Pub)
    monkeypatch.setattr(poller.client, "firmware", lambda *a, **k: {"IBG_SN": "SN284"})
    monkeypatch.setattr(poller.client, "summary", lambda *a, **k: dict(summ))
    import franklinwh_direct_connect_bridge.ha_supervisor as hs
    monkeypatch.setattr(hs, "apply_supervisor_mqtt", lambda *a, **k: None)
    gw = GatewayState(id="g284", label="t", is_mock=True, configured_host="127.0.0.1:1",
                      active_host="127.0.0.1:1")

    async def go():
        stop = asyncio.Event()
        t = asyncio.create_task(poller.run_gateway(s, gw, stop))
        await asyncio.sleep(0.5)
        stop.set()
        await asyncio.wait_for(t, timeout=10)
    asyncio.run(go())
    return gw


def test_a_failed_poll_leaves_the_snapshot_stale(monkeypatch):
    gw = _poll_once(monkeypatch, {"ok": False, "error": "timed out"})
    assert SW.snapshot_age_s(gw) == float("inf")
    ok, why = SW.eligible(gw, config.get_settings())
    assert ok is False and "no state snapshot" in why


def test_a_good_poll_makes_it_fresh(monkeypatch):
    gw = _poll_once(monkeypatch, {"ok": True, "power": {"soc": 50}})
    assert SW.snapshot_age_s(gw) < 5
    assert SW.eligible(gw, config.get_settings())[0] is True
