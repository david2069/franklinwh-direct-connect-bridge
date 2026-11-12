"""Analytics → Explain (#588; owner: "It needs to give the user trends and suggest the
optimal setup for the objectives and setup"): the shown period's trends, findings and
suggestions for the user's objectives, from franklinwh-ha-cloud-analytics insights, on
Local (the bridge's samples) and Cloud (the cloud's totals). Read-only; nothing applied."""
import datetime as dt
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import analytics_insights as ai
from franklinwh_direct_connect_bridge import app as app_module, config, state
from franklinwh_direct_connect_bridge import db as db_module
from franklinwh_direct_connect_bridge.db import MetricsStore

GW = "gw-ex"
H, D = 3600, 86400
PKG = Path(app_module.__file__).parent


@pytest.fixture(autouse=True)
def _gateway(monkeypatch):
    state.register_gateway(GW, "10.0.0.1", "Home")
    monkeypatch.setattr(ai, "mode_and_reserve", lambda gw, host: ("self", 20))
    yield
    state.unregister_gateway(GW)


def _seed(s, start, hours, grid_w):
    for i in range(hours * 60):
        s.insert({"soc": 60, "grid_w": grid_w, "solar_w": 1000, "battery_w": 200,
                  "load_w": 1000 + 200 + grid_w, "generator_w": 0, "mode": "Self"},
                 start + i * 60, gateway_id=GW)


@pytest.fixture
def client(monkeypatch, tmp_path):
    store = MetricsStore(str(tmp_path / "m.db"))
    monkeypatch.setattr(db_module, "get_store", lambda s: store)
    return TestClient(app_module.create_app()), store


def test_local_trends_against_the_previous_window(client):
    c, store = client
    end = (int(time.time()) // H - 1) * H
    start = end - 2 * H
    _seed(store, start - 2 * H, 2, 500)         # previous window: 0.5 kW from the grid
    _seed(store, start, 2, 1000)                # this window: 1 kW from the grid
    r = c.get("/api/analytics/insights", params={"source": "local", "start": start, "end": end,
                                                 "gateway": GW, "objectives": "self_sufficiency"})
    assert r.status_code == 200, r.text
    b = r.json()
    assert {"ratios", "trends", "findings", "suggestions", "objectives"} <= set(b)
    imp = next(t for t in b["trends"] if t["id"] == "grid_import")
    assert imp["direction"] == "up" and imp["vs_previous"] == pytest.approx(1.0, abs=0.1)
    assert b["objectives"] == [{"id": "self_sufficiency", "label": "Most self-sufficiency"}]
    assert b["site"]["mode"] == "self" and b["source"] == "local"
    # no capacity or tariff here: the answer says what would make it fuller
    assert {m["id"] for m in b["missing"]} == {"capacity", "tariff"}


def test_objectives_are_remembered_per_gateway(client):
    c, _ = client
    r = c.put("/api/analytics/insights/objectives", params={"gateway": GW},
              json={"objectives": ["lowest_bill", "battery_care"]})
    assert r.status_code == 200
    end = (int(time.time()) // H) * H
    b = c.get("/api/analytics/insights", params={"source": "local", "start": end - H,
                                                 "end": end, "gateway": GW}).json()
    assert [o["id"] for o in b["objectives"]] == ["lowest_bill", "battery_care"]
    bad = c.put("/api/analytics/insights/objectives", params={"gateway": GW},
                json={"objectives": ["world_peace"]})
    assert bad.status_code == 400


def _payload(kwh):
    return {"unit": "kWh", "series": [
        {"key": "home", "values": [kwh["home"] / 2, kwh["home"] / 2]},
        {"key": "solar", "values": [10.0, 10.0]},
        {"key": "grid_import", "values": [kwh["grid_import"], None]},
        {"key": "grid_export", "values": [-5.0, -5.0]},
        {"key": "battery_discharge", "values": [3.0, 3.0]},
        {"key": "battery_charge", "values": [-3.0, -3.0]},
        {"key": "soc", "values": [50, 60]}]}


def test_cloud_reads_this_period_the_previous_one_and_last_year(client, monkeypatch):
    c, _ = client
    from franklinwh_direct_connect_bridge import cloud_status
    monkeypatch.setenv("FWH_CLOUD_EMAIL", "user@example.invalid")
    monkeypatch.setenv("FWH_CLOUD_PASSWORD", "x")
    monkeypatch.setattr(config, "_settings", None)
    from franklinwh_direct_connect_bridge import providers
    monkeypatch.setattr(providers, "cloud_target_refusal", lambda *a, **k: None)
    asked = []

    def fake(email, password, serial, period, on, today, refresh=False):
        asked.append((period, on.isoformat()))
        return _payload({"home": 40.0, "grid_import": 20.0 if on.year == 2026 and on.month == 10 else 10.0})
    monkeypatch.setattr(cloud_status, "read_energy", fake)
    r = c.get("/api/analytics/insights", params={"source": "cloud", "period": "month",
                                                 "date": "2026-10-05", "gateway": GW})
    assert r.status_code == 200, r.text
    assert sorted(asked) == [("month", "2025-10-05"), ("month", "2026-09-01"), ("month", "2026-10-05")]
    imp = next(t for t in r.json()["trends"] if t["id"] == "grid_import")
    assert imp["direction"] == "up"


def test_cloud_day_views_use_the_hourly_kwh():
    assert ai.cloud_period("day5") == "dayhour" and ai.cloud_period("month") == "month"


def test_cloud_totals_add_up_the_payload():
    t = ai.cloud_totals(_payload({"home": 40.0, "grid_import": 20.0}), days=30)
    assert t == {"home": 40.0, "solar": 20.0, "grid_import": 20.0, "grid_export": 10.0,
                 "battery_discharge": 6.0, "battery_charge": 6.0, "days": 30}
    assert ai.cloud_totals({"unit": "kW", "series": []}, days=1) is None


def test_tariff_summary_from_the_rate_model():
    pricing = {"seasons": [{"id": "all", "months": list(range(1, 13)),
                            "time_periods": {"off_peak": {"buy": 0.20, "sell": 0.05},
                                             "on_peak": {"buy": 0.50, "sell": 0.05}},
                            "blocks": [{"start": "00:00", "end": "15:00", "time_period": "off_peak"},
                                       {"start": "15:00", "end": "21:00", "time_period": "on_peak"},
                                       {"start": "21:00", "end": "24:00", "time_period": "off_peak"}]}]}
    t = ai.tariff_summary(pricing, month=11)
    assert t["kind"] == "tou" and t["peak"] == ["15:00-21:00"]
    assert t["buy_c"] == pytest.approx((18 * 20 + 6 * 50) / 24)
    assert t["sell_c"] == pytest.approx(5.0)
    flat = ai.tariff_summary({"default_rate": {"buy": 0.3, "sell": 0.08}}, month=11)
    assert flat == {"kind": "flat", "buy_c": 30.0, "sell_c": 8.0, "peak": []}
    assert ai.tariff_summary({}, month=11) is None


def test_the_page_has_explain_with_its_results_in_the_dialog():
    html = (PKG / "templates/tabs/analytics.html").read_text()
    js = (PKG / "static/js/analytics_tab.js").read_text()
    assert 'data-testid="analytics-explain"' in html and 'data-testid="explain-dialog"' in html
    for part in ("explain-objectives", "explain-trends", "explain-findings", "explain-suggestions"):
        assert f'data-testid="{part}"' in html
    assert "api/analytics/insights" in js and "api/analytics/insights/objectives" in js
    assert "toast" not in js[js.index("async explain("):js.index("async explain(") + 3000]


def test_pinned_to_the_insights_release():
    assert "franklinwh-ha-cloud-analytics==0.1.27" in (PKG.parents[1] / "pyproject.toml").read_text()


def test_a_window_barely_recorded_is_not_compared_with():
    one = {"series": {k: [1.0] for k in ("home", "solar", "grid_import", "grid_export",
                                         "battery_discharge", "battery_charge")}}
    assert ai.local_totals({**one, "coverage": 0.2}, 7) is None
    assert ai.local_totals({**one, "coverage": 0.9}, 7)["home"] == 1.0
