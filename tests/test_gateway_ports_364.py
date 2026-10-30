"""Each gateway's own ports (#364): Direct Connect on its stored ``port``, the Modbus
client (this bridge) on its stored ``modbus_port`` — not the global ones."""
import sqlite3

import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import app as app_module
from franklinwh_direct_connect_bridge import battery_control as bc
from franklinwh_direct_connect_bridge import client as client_module
from franklinwh_direct_connect_bridge import db, mockgw, state, supervisor
from franklinwh_direct_connect_bridge.config import get_settings


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    state.reset_gateways()
    bc.set_host_override("")
    monkeypatch.delenv("FWH_MODBUS_HOST", raising=False)
    yield
    bc.set_host_override("")
    state.reset_gateways()


@pytest.fixture
def st(tmp_path):
    return db.MetricsStore(str(tmp_path / "m.db"))


@pytest.fixture
def c(st, monkeypatch):
    monkeypatch.setattr(db, "get_store", lambda *a, **k: st)

    async def _noop(*a, **k):
        return None
    monkeypatch.setattr(supervisor, "start_poller", _noop)
    monkeypatch.setattr(supervisor, "stop_poller", _noop)
    monkeypatch.setattr(supervisor, "is_running", lambda gid: False)
    monkeypatch.setattr(mockgw, "start_mock", lambda gid, **k: "127.0.0.1:59999")
    monkeypatch.setattr(mockgw, "stop_mock", lambda gid: None)
    monkeypatch.setattr(client_module, "writes_enabled", lambda s: True)
    return TestClient(app_module.create_app())


def test_direct_connect_uses_the_gateways_own_port(monkeypatch):
    seen = []
    monkeypatch.setattr(client_module, "LocalClient",
                        lambda host, port, **k: seen.append((host, port)))
    gw = state.register_gateway("gw-e", "10.0.0.5", "Emulated", port=9020)
    client_module._client(get_settings(), gw.active_host)
    assert seen == [("10.0.0.5", 9020)]


def test_standard_port_keeps_the_bare_host():
    gw = state.register_gateway("gw-r", "10.0.0.6", "Real")
    assert gw.active_host == gw.configured_host == "10.0.0.6"
    assert bc.effective_target(gw.active_host) == ("10.0.0.6", 502)


def test_modbus_uses_the_gateways_own_modbus_port_not_its_direct_connect_port():
    gw = state.register_gateway("gw-e", "10.0.0.5", "Emulated", port=9020, modbus_port=5020)
    assert bc.effective_target(gw.active_host) == ("10.0.0.5", 5020)


def test_the_override_still_wins_for_the_active_gateway():
    gw = state.register_gateway("gw-e", "10.0.0.5", "Emulated", port=9020, modbus_port=5020)
    bc.set_host_override("192.0.2.50")
    assert bc.effective_target(gw.active_host) == ("192.0.2.50", 502)


def test_api_stores_and_returns_both_ports(c):
    r = c.post("/api/gateways", json={"label": "E", "host": "10.0.0.5",
                                      "port": 9021, "modbus_port": 5021})
    assert r.status_code == 201, r.text
    gid = r.json()["id"]
    assert (r.json()["port"], r.json()["modbus_port"]) == (9021, 5021)
    gw = state.get_gateway(gid)
    assert gw.active_host == "10.0.0.5:9021"
    assert bc.effective_target(gw.active_host) == ("10.0.0.5", 5021)

    r = c.patch(f"/api/gateways/{gid}", json={"port": 9022, "modbus_port": 5022})
    assert r.status_code == 200, r.text
    gw = state.get_gateway(gid)
    assert gw.active_host == "10.0.0.5:9022"
    assert bc.effective_target(gw.active_host) == ("10.0.0.5", 5022)


def test_api_defaults_to_the_standard_ports(c):
    r = c.post("/api/gateways", json={"label": "R", "host": "10.0.0.6"})
    assert (r.json()["port"], r.json()["modbus_port"]) == (9000, 502)


@pytest.mark.parametrize("field", ["port", "modbus_port"])
def test_api_refuses_a_port_out_of_range(c, field):
    r = c.post("/api/gateways", json={"label": "X", "host": "10.0.0.7", field: 70000})
    assert r.status_code == 422


def test_an_existing_roster_gets_the_default_modbus_port(tmp_path):
    path = str(tmp_path / "old.db")
    con = sqlite3.connect(path)
    con.execute("""CREATE TABLE gateways(id TEXT PRIMARY KEY, label TEXT NOT NULL,
                   host TEXT NOT NULL DEFAULT '', port INTEGER NOT NULL DEFAULT 9000,
                   is_default INTEGER NOT NULL DEFAULT 0, enabled INTEGER NOT NULL DEFAULT 1,
                   is_mock INTEGER NOT NULL DEFAULT 0, mock_seed INTEGER,
                   mock_units INTEGER NOT NULL DEFAULT 1, publish_ha INTEGER NOT NULL DEFAULT 1,
                   description TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL DEFAULT 0,
                   updated_at REAL NOT NULL DEFAULT 0)""")
    con.execute("INSERT INTO gateways(id,label,host) VALUES ('g1','Home','10.0.0.8')")
    con.commit()
    con.close()
    assert db.MetricsStore(path).gateway("g1")["modbus_port"] == 502
