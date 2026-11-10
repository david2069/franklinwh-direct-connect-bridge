"""#123 — re-discovery sweeps only when the gateway has really gone, never probes :502,
and "aGate moved" is said only when it moved."""
import asyncio

from franklinwh_direct_connect_bridge import client, config, poller
from franklinwh_direct_connect_bridge.state import GatewayState


def _run(monkeypatch, *, still_here: bool, seconds: float = 5.5, rediscovered=None):
    sweeps, notes = [], []
    s = config.get_settings()
    monkeypatch.setattr(s, "mqtt_enabled", False)
    monkeypatch.setattr(s, "poll_interval", 1)
    monkeypatch.setattr(poller.client, "firmware", lambda *a, **k: {"IBG_SN": "SN1", "IBG_VER": "V1"})
    monkeypatch.setattr(poller.client, "summary", lambda *a, **k: {"ok": False, "error": "timed out"})
    monkeypatch.setattr(poller.client, "still_at_address", lambda host: still_here)
    monkeypatch.setattr(poller.client, "rediscover",
                        lambda *a, **k: sweeps.append(a[1]) or rediscovered)
    monkeypatch.setattr(poller.Notifier, "notify", lambda self, t, m: notes.append(t))
    gw = GatewayState(id="g1", label="real", configured_host="192.0.2.10", active_host="192.0.2.10")

    async def go():
        stop = asyncio.Event()
        t = asyncio.create_task(poller.run_gateway(s, gw, stop))
        await asyncio.sleep(seconds)
        stop.set()
        await asyncio.wait_for(t, timeout=10)
    asyncio.run(go())
    return sweeps, notes, gw


def test_no_sweep_while_the_known_address_still_answers(monkeypatch):
    sweeps, _, _ = _run(monkeypatch, still_here=True)
    assert sweeps == []


def test_sweeps_once_then_backs_off_when_gone(monkeypatch):
    sweeps, notes, _ = _run(monkeypatch, still_here=False)
    assert sweeps == ["192.0.2.10"]                  # not one per failed poll
    assert notes.count("FranklinWH aGate moved") == 0


def test_moved_is_announced_only_for_a_new_address(monkeypatch):
    _, notes, gw = _run(monkeypatch, still_here=False, rediscovered="192.0.2.10")
    assert "FranklinWH aGate moved" not in notes     # same address: not a move
    _, notes, gw = _run(monkeypatch, still_here=False, rediscovered="192.0.2.77")
    assert notes.count("FranklinWH aGate moved") == 1 and gw.active_host == "192.0.2.77"


def test_a_sweep_never_probes_the_modbus_tcp_server(monkeypatch):
    seen = {}

    def fake_scan(targets, **kw):
        seen.update(kw)
        return []
    monkeypatch.setattr(client.discover, "scan", fake_scan)
    client.rediscover(config.get_settings(), "192.0.2.10", "SN1")
    assert seen["ports"] == (client.discover.PORT_SENDMQTT,)
    assert 502 not in seen["ports"]
