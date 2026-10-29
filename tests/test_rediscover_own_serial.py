"""#356 — re-discovery adopts only an aGate with this gateway's own serial, never a host
another registered gateway is using, and the "moved" notice names the gateway."""
import asyncio
from types import SimpleNamespace as NS

from franklinwh_direct_connect_bridge import client, config, poller
from franklinwh_direct_connect_bridge.state import GatewayState, get_state


def _hits(monkeypatch, *hits):
    scans = []
    monkeypatch.setattr(client.discover, "expand_targets", lambda subnet: ["x"])
    monkeypatch.setattr(client.discover, "scan",
                        lambda *a, **k: scans.append(1) or list(hits))
    return scans


def _agate(host, serial):
    return NS(host=host, sendmqtt_confirmed=True, manifest={"IBG_SN": serial})


def test_no_serial_does_not_borrow_the_default_gateways(monkeypatch):
    st = get_state()
    old, st.serial = st.serial, "SN-DEFAULT"
    try:
        scans = _hits(monkeypatch, _agate("192.0.2.5", "SN-DEFAULT"))
        assert client.rediscover(config.get_settings(), "192.0.2.10", None) is None
        assert scans == []                       # no serial: nothing to match, no sweep
    finally:
        st.serial = old


def test_no_serial_match_adopts_nothing(monkeypatch):
    _hits(monkeypatch, _agate("192.0.2.5", "SN-OTHER"))
    assert client.rediscover(config.get_settings(), "192.0.2.10", "SN-MINE") is None


def test_never_adopts_a_host_another_gateway_uses(monkeypatch):
    _hits(monkeypatch, _agate("192.0.2.5", "SN-MINE"))
    assert client.rediscover(config.get_settings(), "192.0.2.10", "SN-MINE",
                             taken={"192.0.2.5"}) is None


def test_adopts_its_own_serial(monkeypatch):
    _hits(monkeypatch, _agate("192.0.2.5", "SN-OTHER"), _agate("192.0.2.77", "SN-MINE"))
    assert client.rediscover(config.get_settings(), "192.0.2.10", "SN-MINE",
                             taken={"192.0.2.5"}) == "192.0.2.77"


def test_poller_passes_other_gateways_hosts_and_names_the_gateway(monkeypatch):
    calls, notes = [], []
    s = config.get_settings()
    monkeypatch.setattr(s, "mqtt_enabled", False)
    monkeypatch.setattr(s, "poll_interval", 1)
    monkeypatch.setattr(poller.client, "firmware", lambda *a, **k: {"IBG_SN": "SN1", "IBG_VER": "V1"})
    monkeypatch.setattr(poller.client, "summary", lambda *a, **k: {"ok": False, "error": "timed out"})
    monkeypatch.setattr(poller.client, "still_at_address", lambda host: False)
    monkeypatch.setattr(poller.client, "rediscover",
                        lambda *a, **k: calls.append(k.get("taken")) or "192.0.2.77")
    monkeypatch.setattr(poller.Notifier, "notify", lambda self, t, m: notes.append(m))
    other = GatewayState(id="g2", label="garage", configured_host="192.0.2.20",
                         active_host="192.0.2.21")
    monkeypatch.setattr(poller, "_all_gateways", lambda: [gw, other])
    gw = GatewayState(id="g1", label="house", configured_host="192.0.2.10",
                      active_host="192.0.2.10")

    async def go():
        stop = asyncio.Event()
        t = asyncio.create_task(poller.run_gateway(s, gw, stop))
        await asyncio.sleep(5.5)
        stop.set()
        await asyncio.wait_for(t, timeout=10)
    asyncio.run(go())
    assert calls and calls[0] == {"192.0.2.20", "192.0.2.21"}
    assert any("house" in m and "192.0.2.77" in m for m in notes)
