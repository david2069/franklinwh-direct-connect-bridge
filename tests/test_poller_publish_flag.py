"""#98 — a gateway with publish_ha off never starts an MQTT publisher.

The poller checked publish_ha when it started, but its self-heal retry ("MQTT never came up,
try again") did not, and with no publisher the retry fired on the first loop. So a mock
created with publish_ha=False was published to Home Assistant at once, while the API said
it wasn't.
"""
import asyncio

from franklinwh_direct_connect_bridge import config, poller
from franklinwh_direct_connect_bridge.state import GatewayState


class _FakePub:
    started = []

    def __init__(self, settings, node, device, **k):
        self.configs = []
        _FakePub.started.append(node)

    def start(self): pass
    def stop(self): pass
    def is_connected(self): return True
    def publish_state(self, st): pass
    def publish_availability(self, online): pass


def _run(monkeypatch, publish_ha: bool) -> list:
    _FakePub.started = []
    s = config.get_settings()
    monkeypatch.setattr(s, "mqtt_enabled", True)
    monkeypatch.setattr(s, "poll_interval", 1)
    monkeypatch.setattr(poller, "MqttPublisher", _FakePub)
    monkeypatch.setattr(poller.client, "firmware", lambda *a, **k: {"IBG_SN": "SN98", "IBG_VER": "V1"})
    monkeypatch.setattr(poller.client, "summary", lambda *a, **k: {"ok": True, "power": {"soc": 50}})
    import franklinwh_direct_connect_bridge.ha_supervisor as hs
    monkeypatch.setattr(hs, "apply_supervisor_mqtt", lambda *a, **k: None)
    gw = GatewayState(id="g98", label="mock", is_mock=True, publish_ha=publish_ha,
                      configured_host="127.0.0.1:1", active_host="127.0.0.1:1")

    async def go():
        stop = asyncio.Event()
        t = asyncio.create_task(poller.run_gateway(s, gw, stop))
        await asyncio.sleep(2.5)                 # past the first loop and its retry check
        stop.set()
        await asyncio.wait_for(t, timeout=10)
    asyncio.run(go())
    return list(_FakePub.started)


def test_publish_off_never_starts_a_publisher(monkeypatch):
    assert _run(monkeypatch, publish_ha=False) == []


def test_publish_on_starts_one(monkeypatch):
    assert _run(monkeypatch, publish_ha=True) == ["sn98"]


def _purge_calls(monkeypatch, publish_ha: bool) -> list:
    calls = []
    from franklinwh_direct_connect_bridge.publish import purge
    monkeypatch.setattr(purge, "purge", lambda settings, node, **k: calls.append(node) or
                        {"found": 3, "removed": 3, "left": []})
    _run(monkeypatch, publish_ha)
    return calls


def test_publish_off_removes_what_is_still_retained(monkeypatch):
    """Upgrade path for #98: gateways published only because of the bug are removed from
    Home Assistant instead of being left 'unavailable'."""
    assert _purge_calls(monkeypatch, publish_ha=False) == ["sn98"]


def test_publish_on_never_purges(monkeypatch):
    assert _purge_calls(monkeypatch, publish_ha=True) == []
