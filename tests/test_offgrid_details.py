"""Off-grid details (owner 2026-11-13): the confirm and progress dialogs name the aGate;
the OFF-GRID dialog has an expandable Details section (mode, SoC, battery, grid, solar,
home, smart circuits, and the generator and V2L only when installed); each off-grid /
on-grid switch saves the same snapshot in the control log."""
import pathlib

from franklinwh_direct_connect_bridge import offgrid_details as od

PKG = pathlib.Path(__file__).resolve().parents[1] / "src" / "franklinwh_direct_connect_bridge"
JS = (PKG / "static" / "js" / "app.js").read_text()
APP = (PKG / "app.py").read_text()
IDX = (PKG / "templates" / "index.html").read_text()

SUMM = {"ok": True,
        "power": {"mode": "Self-Consumption", "soc": 35.7, "battery_w": 1700, "grid_w": 0,
                  "solar_w": 300, "load_w": 2000, "generator_w": 0, "kwh_gen": 0.0},
        "circuits_on": {1: True, 2: False}, "circuit_names": {1: "Pool", 2: ""}}
CIRCUITS = {"circuits": [
    {"id": 1, "name": "Pool", "on": True, "present": True, "watts": 1200},
    {"id": 2, "name": "Circuit 2", "on": False, "present": True, "watts": 0},
    {"id": 3, "name": "Circuit 3", "on": False, "present": False, "watts": None}],
    "carsw": {"enabled": True, "watts": 3300}}
GEN = {"installed": True, "state_name": "Running", "power_w": 4500}


def _rows(**kw):
    return {r["key"]: r["value"] for r in od.rows(SUMM, **kw)}


def test_core_rows_from_the_cached_summary():
    r = _rows()
    assert r["mode"] == "Self-Consumption" and r["soc"] == "36%"
    assert r["battery"] == "discharging 1.7 kW" and r["grid"] == "0.0 kW"
    assert r["solar"] == "0.3 kW" and r["home"] == "2.0 kW"
    assert r["circuits"] == "Pool on, Circuit 2 off"
    assert "generator" not in r and "v2l" not in r


def test_live_circuits_generator_and_v2l_when_installed():
    r = _rows(circuits=CIRCUITS, generator=GEN, v2l_installed=True)
    assert r["circuits"] == "Pool on 1.2 kW, Circuit 2 off"
    assert r["generator"] == "Running, 4.5 kW, 0.0 kWh today"
    assert r["v2l"] == "on, 3.3 kW"


def test_charging_and_line():
    s = {"power": {**SUMM["power"], "battery_w": -500}}
    rows = od.rows(s)
    assert {r["key"]: r["value"] for r in rows}["battery"] == "charging 0.5 kW"
    assert od.line(rows).startswith("Mode Self-Consumption; SoC 36%; Battery charging 0.5 kW")


def test_ui_and_routes():
    assert '@app.get("/api/offgrid/details")' in APP
    sw = APP[APP.index('def api_set_offgrid'):APP.index('@app.get("/api/ha/dashboard-yaml")')]
    assert "offgrid_details.line(" in sw          # the snapshot goes in the control log
    so = JS[JS.index("async setOffgrid(on)"):JS.index("// The Direct Connect and Modbus")]
    assert "selectedGatewayLabel" in so           # confirm + progress name the aGate
    for tid in ("offgrid-details-toggle", "offgrid-details"):
        assert f'data-testid="{tid}"' in IDX


def _app(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from franklinwh_direct_connect_bridge import app as app_module, state, config, environment, db
    from franklinwh_direct_connect_bridge.db import MetricsStore
    store = MetricsStore(str(tmp_path / "m.db"))
    monkeypatch.setattr(environment, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "_settings", None)
    monkeypatch.setattr(db, "get_store", lambda s: store)
    c = TestClient(app_module.create_app())
    monkeypatch.setattr(state, "_gateways", {})
    monkeypatch.setattr(state, "_default_id", None)
    gw = state.register_gateway("g1", "127.0.0.1:1", "House")
    gw.last_summary = SUMM
    return c, gw, store


def test_details_endpoint_reads_circuits_and_generator(tmp_path, monkeypatch):
    from franklinwh_direct_connect_bridge import client
    c, gw, _ = _app(tmp_path, monkeypatch)
    gw.generator_installed = True
    monkeypatch.setattr(client, "circuits", lambda s, host=None, override=None: CIRCUITS)
    monkeypatch.setattr(client, "generator", lambda s, host=None: GEN)
    r = c.get("/api/offgrid/details?gateway=g1").json()
    got = {x["key"]: x["value"] for x in r["rows"]}
    assert got["generator"].startswith("Running") and got["v2l"] == "on, 3.3 kW"
    assert r["errors"] == {}


def test_details_endpoint_survives_a_failed_read(tmp_path, monkeypatch):
    from franklinwh_direct_connect_bridge import client
    c, gw, _ = _app(tmp_path, monkeypatch)

    def boom(*a, **k):
        raise OSError("unreachable")
    monkeypatch.setattr(client, "circuits", boom)
    r = c.get("/api/offgrid/details?gateway=g1").json()
    got = {x["key"]: x["value"] for x in r["rows"]}
    assert got["circuits"] == "Pool on, Circuit 2 off" and "v2l" not in got
    assert r["errors"] == {"circuits": "unreachable"}


def test_switch_logs_the_snapshot(tmp_path, monkeypatch):
    from franklinwh_direct_connect_bridge import client
    c, gw, store = _app(tmp_path, monkeypatch)
    monkeypatch.setattr(client, "set_offgrid", lambda s, on, soc, host=None: {"ok": True})
    c.post("/api/offgrid?gateway=g1", json={"on": True, "soc": 5, "confirm": True})
    detail = store.control_log(limit=1)[0]["detail"]
    assert detail.startswith("reconnect_soc=5% · Mode Self-Consumption; SoC 36%")
