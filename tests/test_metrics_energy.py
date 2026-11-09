"""Owner, 2026-11-09: Local shows the same quantity as Cloud. Day (hourly), Week, Month,
Year and Lifetime are kWh per hour, day, month or year (power summed over each slot),
with the six series Cloud has; Day (5-min) is power in kW."""
import time

import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import app as app_module, state
from franklinwh_direct_connect_bridge import db as db_module
from franklinwh_direct_connect_bridge.db import MetricsStore

GW = "gw-en"
H = 3600


@pytest.fixture(autouse=True)
def _gateway():
    state.register_gateway(GW, "10.0.0.1", "Home")
    yield
    state.unregister_gateway(GW)


def _store(tmp_path, start):
    s = MetricsStore(str(tmp_path / "m.db"))
    # two hours at 60 s: 2 kW solar, 0.5 kW home, battery charging 1 kW, exporting 0.5 kW
    for i in range(120):
        s.insert({"soc": 50 + i / 10, "grid_w": -500, "solar_w": 2000, "battery_w": -1000,
                  "load_w": 500, "generator_w": 0, "mode": "Self"}, start + i * 60, gateway_id=GW)
    return s


def test_kwh_per_slot_with_clouds_six_series(monkeypatch, tmp_path):
    start = (int(time.time()) // H - 48) * H
    store = _store(tmp_path, start)
    monkeypatch.setattr(db_module, "get_store", lambda s: store)
    edges = [start, start + H, start + 2 * H, start + 3 * H]
    r = TestClient(app_module.create_app()).get(
        "/api/metrics/energy", params={"edges": ",".join(map(str, edges)), "gateway": GW})
    assert r.status_code == 200
    b = r.json()
    assert b["unit"] == "kWh" and b["starts"] == edges[:-1]
    s = b["series"]
    assert set(s) == {"home", "solar", "battery_discharge", "battery_charge", "grid_import", "grid_export"}
    assert s["solar"][0] == pytest.approx(2.0, abs=0.05)
    assert s["home"][1] == pytest.approx(0.5, abs=0.05)
    assert s["battery_charge"][0] == pytest.approx(1.0, abs=0.05)
    assert s["grid_export"][1] == pytest.approx(0.5, abs=0.05)
    assert s["grid_import"][0] == 0
    assert s["solar"][2] is None                     # no samples: empty, never 0
    assert b["soc"][0] == pytest.approx(53, abs=0.5) and b["soc"][2] is None
    assert 0.6 < b["coverage"] <= 0.67               # 2 of 3 hours
    assert b["first_ts"] == start


def test_bad_edges_are_a_400(monkeypatch, tmp_path):
    monkeypatch.setattr(db_module, "get_store", lambda s: _store(tmp_path, 0))
    c = TestClient(app_module.create_app())
    for e in ("", "5", "10,5", "a,b", ",".join(str(i) for i in range(500))):
        assert c.get("/api/metrics/energy", params={"edges": e, "gateway": GW}).status_code == 400


from pathlib import Path  # noqa: E402

ROOT = Path(app_module.__file__).parent
JS = (ROOT / "static" / "js" / "analytics_tab.js").read_text()
HTML = (ROOT / "templates" / "tabs" / "analytics.html").read_text()


def test_the_page_reads_kwh_slots_and_shows_kw_for_a_day():
    assert "api/metrics/energy?edges=" in JS and "function analyticsSlotEdges(" in JS
    assert "get energyMode() { return this.period !== 'day5'; }" in JS
    assert "get unit() { return this.energyMode ? 'kWh' : 'kW'; }" in JS
    assert "text: self.unit" in JS and "text: 'W'" not in JS
    assert "p[key] / scale" in JS                    # power in kW, SoC stays %
    for k in ("battery_discharge", "battery_charge", "grid_import", "grid_export"):
        assert f"key: '{k}'" in JS
    assert 'x-for="m in chips"' in HTML


def test_until_a_style_is_picked_a_day_is_lines_and_kwh_is_bars_like_cloud():
    assert "get chartType() { return this.style || (this.energyMode ? 'bars' : 'line'); }" in JS
