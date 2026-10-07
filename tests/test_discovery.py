"""Phase 3 — re-discovery picks the right host; active-host indirection."""

from types import SimpleNamespace as NS

from franklinwh_direct_connect_bridge import client
from franklinwh_direct_connect_bridge.config import Settings
from franklinwh_direct_connect_bridge.state import get_state


def _reset_state():
    st = get_state()
    st.active_host = None
    st.serial = None
    st.firmware = None
    return st


def test_active_host_prefers_rediscovered():
    st = _reset_state()
    s = Settings(fwh_host="192.0.2.110")
    assert client.active_host(s) == "192.0.2.110"
    st.active_host = "192.0.2.250"
    assert client.active_host(s) == "192.0.2.250"
    _reset_state()


def test_rediscover_prefers_matching_serial(monkeypatch):
    st = _reset_state()
    st.serial = "SN-KNOWN"
    s = Settings(fwh_host="192.0.2.110")
    hits = [
        NS(host="192.0.2.5", sendmqtt_confirmed=True, manifest={"IBG_SN": "SN-OTHER"}),
        NS(host="192.0.2.240", sendmqtt_confirmed=True, manifest={"IBG_SN": "SN-KNOWN"}),
    ]
    monkeypatch.setattr(client.discover, "expand_targets", lambda subnet: ["x"])
    monkeypatch.setattr(client.discover, "scan", lambda *a, **k: hits)
    assert client.rediscover(s) == "192.0.2.240"      # matched by serial, not first hit
    assert get_state().active_host == "192.0.2.240"   # adopted
    _reset_state()


def test_rediscover_none_when_no_agate(monkeypatch):
    _reset_state()
    s = Settings(fwh_host="192.0.2.110")
    monkeypatch.setattr(client.discover, "expand_targets", lambda subnet: ["x"])
    monkeypatch.setattr(client.discover, "scan", lambda *a, **k: [])
    assert client.rediscover(s) is None
    _reset_state()
