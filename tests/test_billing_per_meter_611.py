"""#611: billing is per meter. Two gateways on one meter share one bill: one set of fixed
charges, demand from the meter's combined peak, and energy by how each grid CT is wired
(its own part of the meter: summed; the whole meter: counted once)."""
import datetime as dt

import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import app as app_module, billing, config, db, environment, state
from franklinwh_direct_connect_bridge.db import MetricsStore

AUG = dt.datetime(2026, 8, 20, 12, 0, 0)


def _setup(tmp_path, ct_a="", ct_b="", demand=False):
    st = MetricsStore(str(tmp_path / "m.db"))
    sid = st.create_site(sid="s1", name="Home")["id"]
    st.create_utility(uid="u1", name="AGL", network_dnsp="Ausgrid")
    pricing = {"default_rate": {"buy": 0.30, "sell": 0.05}}
    extra = {}
    if demand:
        pricing.update(demand_rate=1.0, demand_interval_min=30, demand_charge_basis="per_kw_month")
        extra["demand_window"] = {"start": "00:00", "end": "23:59"}
    st.create_tariff(tid="t1", utility_id="u1", name="Flat 30c", billing_cycle_day=1,
                     pricing=pricing, **extra,
                     fixed_charges=[{"type": "supply", "frequency": "daily", "rate": 1.0,
                                     "tax_rate": 0}])
    st.create_meter(mid="m1", site_id=sid, utility_id="u1", tariff_id="t1", is_default=True)
    st.create_gateway(gw_id="gwA", label="A", is_mock=True, is_default=True)
    st.create_gateway(gw_id="gwB", label="B", is_mock=True)
    st.update_gateway("gwA", meter_id="m1", grid_ct=ct_a)
    st.update_gateway("gwB", meter_id="m1", grid_ct=ct_b)
    billing._TRACKERS.clear()
    return st


def _run(st, a_w, b_w, start=AUG, minutes=60):
    """Both gateways poll once a minute for ``minutes``."""
    for i in range(minutes + 1):
        t = start + dt.timedelta(minutes=i)
        billing.billing_tick(st, "gwA", a_w, now=t)
        billing.billing_tick(st, "gwB", b_w, now=t + dt.timedelta(seconds=20))


def test_one_meter_two_gateways_one_bill(tmp_path):
    st = _setup(tmp_path)
    _run(st, 1000.0, 1000.0)
    a = billing.billing_read(st, "gwA", now=AUG + dt.timedelta(hours=1))
    b = billing.billing_read(st, "gwB", now=AUG + dt.timedelta(hours=1))
    assert a == b                                              # one meter, one bill
    assert a["energy.period_import_kwh"] == pytest.approx(2.0, abs=0.05)   # own parts: summed
    # Roll into September: ONE closed period, with the fixed charges once (31 days × $1).
    billing.billing_tick(st, "gwA", 0.0, now=dt.datetime(2026, 9, 1, 0, 0, 30))
    billing.billing_tick(st, "gwB", 0.0, now=dt.datetime(2026, 9, 1, 0, 0, 40))
    rows = st.billing_periods()
    assert len(rows) == 1
    assert rows[0]["meter_id"] == "m1"
    assert rows[0]["fixed_total"] == pytest.approx(31.0)
    assert rows[0]["import_kwh"] == pytest.approx(2.0, abs=0.05)


def test_whole_meter_ct_counts_once(tmp_path):
    st = _setup(tmp_path, ct_a="meter", ct_b="meter")
    _run(st, 1000.0, 1000.0)
    pts = billing.billing_read(st, "gwB", now=AUG + dt.timedelta(hours=1))
    assert pts["energy.period_import_kwh"] == pytest.approx(1.0, abs=0.05)


def test_the_meter_nets_one_gateways_export_against_the_others_import(tmp_path):
    st = _setup(tmp_path, demand=True)
    _run(st, 2000.0, -2000.0)
    pts = billing.billing_read(st, "gwA", now=AUG + dt.timedelta(hours=1))
    assert pts["energy.period_import_kwh"] == pytest.approx(0.0, abs=0.01)
    assert pts["demand.peak_kw"] == pytest.approx(0.0, abs=0.01)


def test_demand_is_the_combined_peak(tmp_path):
    st = _setup(tmp_path, demand=True)
    _run(st, 2000.0, 1000.0)
    pts = billing.billing_read(st, "gwA", now=AUG + dt.timedelta(hours=1))
    assert pts["demand.peak_kw"] == pytest.approx(3.0, abs=0.1)


def test_a_silent_gateway_is_left_out_not_counted_forever(tmp_path):
    st = _setup(tmp_path)
    billing.billing_tick(st, "gwB", 5000.0, now=AUG)           # B reports once, then goes quiet
    for i in range(1, 61):
        billing.billing_tick(st, "gwA", 1000.0, now=AUG + dt.timedelta(minutes=i))
    pts = billing.billing_read(st, "gwA", now=AUG + dt.timedelta(hours=1))
    assert pts["energy.period_import_kwh"] < 1.5               # not 1 kWh + 5 kWh of stale B


def test_saved_state_from_before_611_carries_over(tmp_path):
    st = _setup(tmp_path)
    old = billing.BillingTracker._blank()
    old.update(period_start=dt.datetime(2026, 8, 1).timestamp(), tariff_id="t1",
               period_import_kwh=10.0, import_cost=3.0)
    import json
    st.set_config("billing_state:gwA", json.dumps(old))
    st.set_config("billing_state:gwB", json.dumps(dict(old, period_import_kwh=4.0, import_cost=1.2)))
    pts = billing.billing_read(st, "gwA", now=AUG)
    assert pts["energy.period_import_kwh"] == pytest.approx(14.0)
    assert pts["energy.import_cost"] == pytest.approx(4.2)


@pytest.fixture
def api(tmp_path, monkeypatch):
    st = _setup(tmp_path)
    monkeypatch.setattr(environment, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "_settings", None)
    monkeypatch.setattr(db, "get_store", lambda s: st)
    for g in ("gwA", "gwB"):
        state.register_gateway(g, "10.0.0.9", g)
    c = TestClient(app_module.create_app())
    c.store = st
    yield c
    for g in ("gwA", "gwB"):
        state.unregister_gateway(g)
    config._settings = None


def test_history_for_either_gateway_shows_the_meters_periods(api):
    st = api.store
    _run(st, 1000.0, 1000.0)
    billing.billing_tick(st, "gwA", 0.0, now=dt.datetime(2026, 9, 1, 0, 0, 30))
    for g in ("gwA", "gwB"):
        rows = api.get(f"/api/billing/history?gateway={g}").json()["periods"]
        assert len(rows) == 1 and rows[0]["meter_id"] == "m1"


def test_grid_ct_is_a_gateway_setting(api):
    r = api.patch("/api/gateways/gwB", json={"grid_ct": "meter"})
    assert r.status_code == 200, r.text
    assert r.json()["grid_ct"] == "meter"
    assert api.patch("/api/gateways/gwB", json={"grid_ct": "both"}).status_code == 422


def test_the_gateway_editor_asks_what_the_grid_ct_measures():
    from pathlib import Path
    root = Path(billing.__file__).parent
    html = (root / "templates/tabs/settings.html").read_text()
    js = (root / "static/js/settings_tab.js").read_text()
    assert 'data-testid="gw-grid-ct"' in html and 'x-model="gwEdit.grid_ct"' in html
    assert "body.grid_ct = e.grid_ct" in js
