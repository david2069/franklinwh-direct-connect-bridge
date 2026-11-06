"""Health → Rediscovered is per gateway (#163).

It was ``host != settings.fwh_host``, so with several gateways every gateway except the
one at the global host showed "Rediscovered: true", a mock included. It is true only when
re-discovery moved this gateway (its active address differs from the one it was set up
with), and n/a (None) for a mock.
"""

import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import app as app_module
from franklinwh_direct_connect_bridge import state as state_module


@pytest.fixture(autouse=True)
def _clean_registry():
    state_module.reset_gateways()
    yield
    state_module.reset_gateways()


def _summary(c, gw_id):
    return c.get(f"/api/gateways/{gw_id}/summary").json()


def test_rediscovered_is_per_gateway_not_the_global_host():
    home = state_module.register_gateway("gw-home", "192.0.2.10", "Home")
    shed = state_module.register_gateway("gw-shed", "192.0.2.20", "Shed")
    moved = state_module.register_gateway("gw-moved", "192.0.2.30", "Garage")
    moved.active_host = "192.0.2.31"                 # re-discovery adopted a new address
    mock = state_module.register_gateway("gw-mock", "127.0.0.1:9001", "Mock", is_mock=True)
    # The summary the poller cached still carries the old global-host comparison.
    for g in (home, shed, moved, mock):
        g.last_summary = {"ok": True, "rediscovered": True, "power": {"soc": 50}}
    c = TestClient(app_module.create_app())
    assert _summary(c, "gw-home")["rediscovered"] is False
    assert _summary(c, "gw-shed")["rediscovered"] is False
    assert _summary(c, "gw-moved")["rediscovered"] is True
    assert _summary(c, "gw-mock")["rediscovered"] is None


def test_health_shows_n_a_when_rediscovered_is_unknown():
    from pathlib import Path
    import franklinwh_direct_connect_bridge as pkg
    html = (Path(pkg.__file__).parent / "templates/tabs/health.html").read_text()
    row = next(l for l in html.splitlines() if ">Rediscovered<" in l)
    assert "?? false" not in row
    assert "n/a" in row
