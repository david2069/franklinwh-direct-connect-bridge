"""Energy-flow Sankey — decomposition unit tests + endpoint + UI wiring.
Ported from the FranklinWH Modbus Bridge; the decomposition module is verbatim."""
import pathlib
from fastapi.testclient import TestClient
from franklinwh_direct_connect_bridge import app as app_module
from franklinwh_direct_connect_bridge import energy_flow as ef
from franklinwh_direct_connect_bridge import environment, db

ROOT = pathlib.Path(__file__).resolve().parents[1] / "src/franklinwh_direct_connect_bridge"


def test_split_sample_merit_order():
    # 5 kW solar, 1 kW home, charging 3 kW (battery_w -3000), exporting 1 kW (grid_w -1000)
    arcs = ef.split_sample({"solar_w": 5000, "home_w": 1000, "battery_w": -3000, "grid_w": -1000})
    assert arcs["solar_to_home"] == 1000          # house first
    assert arcs["solar_to_battery"] == 3000       # then battery
    assert arcs["solar_to_grid"] == 1000          # remainder exported
    assert arcs["grid_to_home"] == 0 and arcs["battery_to_home"] == 0


def test_split_sample_discharge_to_home():
    # no solar, 2 kW home, discharging 2 kW (battery_w +2000), no grid
    arcs = ef.split_sample({"solar_w": 0, "home_w": 2000, "battery_w": 2000, "grid_w": 0})
    assert arcs["battery_to_home"] == 2000
    assert arcs["grid_to_home"] == 0


def test_integrate_kwh_and_quality():
    # two samples an hour apart, steady 1 kW solar → 1 kW home
    rows = [
        {"ts": 0, "solar_w": 1000, "home_w": 1000, "battery_w": 0, "grid_w": 0},
        {"ts": 3600, "solar_w": 1000, "home_w": 1000, "battery_w": 0, "grid_w": 0},
    ]
    out = ef.integrate(rows)
    assert round(out["solar_to_home"], 2) == 1.0   # 1 kW for 1 h = 1 kWh
    assert out["samples"] == 2 and out["residual_kwh"] == 0.0


def test_energy_flow_endpoint_shape(monkeypatch):
    # No metrics store in the test env → endpoint takes its empty-data path.
    monkeypatch.setattr(db, "get_store", lambda *a, **k: None)
    c = TestClient(app_module.create_app())
    r = c.get("/api/energy/flow")
    assert r.status_code == 200
    d = r.json()
    assert set(d["flows"]) == set(ef.FLOWS)
    assert "nodes" in d and "quality" in d and "coverage" in d["quality"]
    # bad date is a 400, not a 500
    assert c.get("/api/energy/flow?day=nonsense").status_code == 400


def test_energy_flow_ui_wired():
    dash = (ROOT / "templates/tabs/dashboard.html").read_text()
    index = (ROOT / "templates/index.html").read_text()
    assert "energyFlowCard()" in dash and 'x-ref="sankey"' in dash
    assert "sankey.js" in index and "energy_flow_card.js" in index
    # node totals use x-if (x-show would evaluate nodes.* when null)
    assert 'x-if="nodes"' in dash
