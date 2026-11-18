"""#364: a gateway's own Direct Connect port (roster ``port``) is the one its requests use.
The default (9000) leaves the global FWH port setting in charge, as before."""
import pytest

from franklinwh_direct_connect_bridge import client, config, state


@pytest.fixture(autouse=True)
def _addr(monkeypatch):
    monkeypatch.setattr(client, "LocalClient", lambda h, port, **kw: (h, port))


@pytest.fixture
def gws():
    state.register_gateway("gw-p1", "10.0.0.31", port=9100)
    state.register_gateway("gw-p2", "10.0.0.32")
    yield
    state.unregister_gateway("gw-p1")
    state.unregister_gateway("gw-p2")


def test_a_gateways_own_port_is_used(gws):
    assert client._client(config.get_settings(), host="10.0.0.31") == ("10.0.0.31", 9100)


def test_a_default_port_gateway_uses_the_global_setting(gws, monkeypatch):
    s = config.get_settings()
    monkeypatch.setattr(s, "fwh_port", 9001)
    assert client._client(s, host="10.0.0.32")[1] == 9001


def test_an_explicit_host_port_still_wins(gws):
    assert client._client(config.get_settings(), host="10.0.0.31:9300")[1] == 9300
