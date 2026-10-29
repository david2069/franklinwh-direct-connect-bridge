"""#379 — the VPP monitor watches every gateway, not only the default, and keeps each
one's state apart, so the All gateways view (#383) shows each gateway's own dispatch."""
import inspect

import pytest

from franklinwh_direct_connect_bridge import app as app_module, battery_control, state, vpp_monitor


class _Store:
    def __init__(self):
        self.events = []

    def __getattr__(self, name):
        return lambda *a, **k: self.events.append((name, a, k))


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    vpp_monitor.reset()
    monkeypatch.setattr(battery_control, "current", lambda host=None: {"active": None})
    yield
    vpp_monitor.reset()


def test_one_gateways_dispatch_is_not_another_gateways_transition():
    st = _Store()
    for host in ("10.0.0.1", "10.0.0.2"):
        vpp_monitor.check(host, st, notify=False, snapshot={"vpp": False})
    a = vpp_monitor.check("10.0.0.1", st, notify=False, snapshot={"vpp": True}, label="House")
    b = vpp_monitor.check("10.0.0.2", st, notify=False, snapshot={"vpp": False}, label="Garage")
    assert a["event"] == "start" and b["changed"] is False
    started = [e for e in st.events if "vpp-start" in e[1]]
    assert len(started) == 1 and started[0][1][-1].startswith("House: ")


def test_the_loop_covers_every_gateway_and_never_picks_the_default():
    src = inspect.getsource(app_module.create_app)
    body = src[src.index("def _vpp_loop():"):]
    body = body[:body.index("_t.sleep(interval)")]
    assert "for _gw in gws:" in body and "state.gateways()" in body
    assert "default_gateway()" not in body


def test_a_second_gateways_remote_dispatch_shows_on_its_own_row(monkeypatch):
    from fastapi.testclient import TestClient
    a = state.GatewayState(id="gw-a", label="A", configured_host="10.0.0.1", active_host="10.0.0.1")
    b = state.GatewayState(id="gw-b", label="B", configured_host="10.0.0.2", active_host="10.0.0.2")
    monkeypatch.setitem(state._gateways, "gw-a", a)
    monkeypatch.setitem(state._gateways, "gw-b", b)
    monkeypatch.setattr(state, "_default_id", "gw-a")
    monkeypatch.setattr(battery_control, "holds_force", lambda *h: False)
    a.vpp_active, b.vpp_active = False, True
    rows = {r["id"]: r for r in TestClient(app_module.create_app()).get("/api/site/status").json()["gateways"]}
    assert rows["gw-b"]["vpp_kind"] == "remote" and rows["gw-a"]["vpp_kind"] is None
