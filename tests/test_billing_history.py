"""FEAT-BILLING-SERVICE — closed-period persistence (billing_periods) + the overview/history
endpoints. The live period-to-date engine (billing.py) already existed; this covers the new
rollover snapshot + the Energy-Costs backend."""
import datetime as dt

from fastapi.testclient import TestClient

from franklinwh_local_bridge import app as app_module, config, environment, db, billing
from franklinwh_local_bridge.db import MetricsStore


def _setup(tmp_path):
    st = MetricsStore(str(tmp_path / "m.db"))
    sid = st.create_site(sid="s1", name="Home")["id"]
    st.create_utility(uid="u1", name="AGL", network_dnsp="Ausgrid")
    st.create_tariff(tid="t1", utility_id="u1", name="Flat 30c", billing_cycle_day=1,
                     pricing={"default_rate": {"buy": 0.30, "sell": 0.05}})
    st.create_meter(mid="m1", site_id=sid, utility_id="u1", tariff_id="t1", is_default=True)
    billing._TRACKERS.clear()
    return st


def test_period_closes_to_history_on_rollover(tmp_path):
    st = _setup(tmp_path)
    tr = billing.BillingTracker()
    cfg = billing._billing_cfg(st, None)
    assert cfg is not None
    # August: import 1 kW for 1 h ≈ 1 kWh @ $0.30
    tr.update(st, "default", 1000.0, cfg, dt.datetime(2026, 8, 20, 12, 0, 0))
    tr.update(st, "default", 1000.0, cfg, dt.datetime(2026, 8, 20, 13, 0, 0))
    assert st.billing_periods() == []                    # nothing closed yet
    # roll into September → closes the August period
    tr.update(st, "default", 0.0, cfg, dt.datetime(2026, 9, 1, 0, 0, 0))
    rows = st.billing_periods()
    assert len(rows) == 1
    r = rows[0]
    assert r["retailer"] == "AGL" and r["network"] == "Ausgrid" and r["tariff_name"] == "Flat 30c"
    assert r["import_kwh"] >= 0.9 and r["import_cost"] > 0 and r["net_total"] > 0
    assert dt.datetime.fromtimestamp(r["period_start"]).month == 8
    assert dt.datetime.fromtimestamp(r["period_end"]).month == 9


def test_empty_period_is_not_persisted(tmp_path):
    st = _setup(tmp_path)
    tr = billing.BillingTracker()
    cfg = billing._billing_cfg(st, None)
    # establish a period with no import, then roll over → nothing to record
    tr.update(st, "default", 0.0, cfg, dt.datetime(2026, 8, 20, 12, 0, 0))
    tr.update(st, "default", 0.0, cfg, dt.datetime(2026, 9, 1, 0, 0, 0))
    assert st.billing_periods() == []


def test_force_close_snapshots_current_period_and_dedups(tmp_path):
    st = _setup(tmp_path)
    # accrue ~1 kWh @ $0.30 in the LIVE tracker (the one force_close reads)
    billing.billing_tick(st, None, 1000.0, now=dt.datetime(2026, 8, 20, 12, 0, 0))
    billing.billing_tick(st, None, 1000.0, now=dt.datetime(2026, 8, 20, 13, 0, 0))
    assert st.billing_periods() == []                       # nothing closed yet
    # manual close now → snapshots the current (August) period into history
    r = billing.force_close_current(st, None, now=dt.datetime(2026, 8, 20, 13, 0, 0))
    assert r["ok"] and r["closed"] and r["period"]["net_total"] > 0
    rows = st.billing_periods()
    assert len(rows) == 1 and rows[0]["import_kwh"] >= 0.9 and rows[0]["net_total"] > 0
    ps = rows[0]["period_start"]
    # keep accruing, close again → REPLACES the same-period row (no duplicate)
    billing.billing_tick(st, None, 1000.0, now=dt.datetime(2026, 8, 20, 14, 0, 0))
    billing.force_close_current(st, None, now=dt.datetime(2026, 8, 20, 14, 0, 0))
    rows2 = st.billing_periods()
    assert len(rows2) == 1 and rows2[0]["period_start"] == ps          # dedup: still one row
    assert rows2[0]["import_kwh"] >= rows[0]["import_kwh"]             # updated with more accrual


def test_force_close_snapshots_fixed_only_period(tmp_path):
    """A period with only a standing charge (no energy, tracker never ticked) is still a real
    bill — a manual close anchors the period and records it."""
    st = MetricsStore(str(tmp_path / "m.db"))
    sid = st.create_site(sid="s1", name="Home")["id"]
    st.create_utility(uid="u1", name="AGL", network_dnsp="Ausgrid")
    st.create_tariff(tid="t1", utility_id="u1", name="Supply only", billing_cycle_day=1,
                     pricing={"default_rate": {"buy": 0.30, "sell": 0.05}},
                     fixed_charges=[{"type": "supply", "frequency": "daily", "rate": 1.0, "tax_rate": 0}])
    st.create_meter(mid="m1", site_id=sid, utility_id="u1", tariff_id="t1", is_default=True)
    billing._TRACKERS.clear()
    r = billing.force_close_current(st, None, now=dt.datetime(2026, 8, 20, 12, 0, 0))
    assert r["ok"] and r["closed"]
    row = st.billing_periods()[0]
    assert row["fixed_total"] > 0 and row["net_total"] > 0
    assert (row["import_kwh"] or 0) == 0                        # no energy, fixed only


def test_force_close_refuses_empty_period(tmp_path):
    st = _setup(tmp_path)
    billing.billing_tick(st, None, 0.0, now=dt.datetime(2026, 8, 20, 12, 0, 0))
    r = billing.force_close_current(st, None, now=dt.datetime(2026, 8, 20, 12, 0, 0))
    assert r["ok"] is False and "accru" in r["reason"]
    assert st.billing_periods() == []


def test_billing_close_endpoint(tmp_path, monkeypatch):
    st = _setup(tmp_path)
    monkeypatch.setattr(environment, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "_settings", None)
    monkeypatch.setattr(db, "get_store", lambda s: st)
    billing.billing_tick(st, None, 1000.0, now=dt.datetime(2026, 8, 20, 12, 0, 0))
    billing.billing_tick(st, None, 1000.0, now=dt.datetime(2026, 8, 20, 13, 0, 0))
    c = TestClient(app_module.create_app())
    out = c.post("/api/billing/close").json()
    assert out["ok"] and out["closed"]
    assert len(c.get("/api/billing/history").json()["periods"]) == 1


MODBUS_HISTORY = [
    # a real closed period (August): reward=bonus, charge=export-charge, net negative (credit)
    {"period_start": 1788184800.0, "period_end": 1788220800.0, "demand_peak_kw": 0.1,
     "demand_charge": 1.27, "reward_kwh": 76.54, "reward_credit": 2.95, "charge_kwh": 95.34,
     "charge_net_kwh": 88.51, "charge_cost": 1.2, "fixed_charges": 0.0, "net_total": -1.75,
     "energy_cost": 0.0, "energy_credit": 0.0, "retailer": "AGL", "network": "Ausgrid", "plan_version": 1},
    {"period_start": 1788220800.0, "period_end": 1788184800.0, "net_total": 0.0},          # end<=start → skip
    {"period_start": 1785000000.0, "period_end": 1785500000.0, "net_total": 0.0,           # all-zero → skip
     "energy_cost": 0.0, "fixed_charges": 0.0, "charge_cost": 0.0, "reward_credit": 0.0, "demand_charge": 0.0},
]


def test_import_modbus_periods_maps_skips_and_dedups(tmp_path):
    st = _setup(tmp_path)
    r = billing.import_modbus_periods(st, MODBUS_HISTORY, gateway_id="gwX")
    assert r["ok"] and r["imported"] == 1 and r["skipped"] == 2
    row = st.billing_periods(gateway_id="gwX")[0]
    assert row["net_total"] == -1.75 and row["bonus_credit"] == 2.95 and row["export_charge"] == 1.2
    assert row["demand_charge"] == 1.27 and row["demand_peak_kw"] == 0.1
    assert row["retailer"] == "AGL" and row["network"] == "Ausgrid"
    # re-import is idempotent — same (gateway, period_start) row is replaced, not duplicated
    billing.import_modbus_periods(st, MODBUS_HISTORY, gateway_id="gwX")
    assert len(st.billing_periods(gateway_id="gwX")) == 1


def test_billing_import_endpoint(tmp_path, monkeypatch):
    st = _setup(tmp_path)
    monkeypatch.setattr(environment, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "_settings", None)
    monkeypatch.setattr(db, "get_store", lambda s: st)
    c = TestClient(app_module.create_app())
    out = c.post("/api/billing/import?gateway=gwX", json={"periods": MODBUS_HISTORY}).json()
    assert out["ok"] and out["imported"] == 1 and out["skipped"] == 2
    assert len(c.get("/api/billing/history?gateway=gwX").json()["periods"]) == 1


def test_billing_import_modbus_endpoint(tmp_path, monkeypatch):
    st = _setup(tmp_path)
    monkeypatch.setattr(environment, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "_settings", None)
    monkeypatch.setattr(db, "get_store", lambda s: st)
    monkeypatch.setattr(billing, "fetch_modbus_history",
                        lambda url, username="admin", password="admin", **k: list(MODBUS_HISTORY))
    c = TestClient(app_module.create_app())
    # dry run previews the count without writing
    dry = c.post("/api/billing/import-modbus?gateway=gwX",
                 json={"source_url": "http://x:8100", "dry_run": True}).json()
    assert dry["ok"] and dry["dry_run"] and dry["available"] == 3
    assert c.get("/api/billing/history?gateway=gwX").json()["periods"] == []
    # real fetch + import
    out = c.post("/api/billing/import-modbus?gateway=gwX", json={"source_url": "http://x:8100"}).json()
    assert out["ok"] and out["imported"] == 1 and out["skipped"] == 2 and out["fetched"] == 3
    assert len(c.get("/api/billing/history?gateway=gwX").json()["periods"]) == 1


def test_billing_import_modbus_requires_url(tmp_path, monkeypatch):
    st = _setup(tmp_path)
    monkeypatch.setattr(environment, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "_settings", None)
    monkeypatch.setattr(db, "get_store", lambda s: st)
    out = TestClient(app_module.create_app()).post("/api/billing/import-modbus", json={"source_url": ""}).json()
    assert out["ok"] is False and "URL" in out["reason"]


def test_billing_overview_and_history_api(tmp_path, monkeypatch):
    st = _setup(tmp_path)
    monkeypatch.setattr(environment, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "_settings", None)
    monkeypatch.setattr(db, "get_store", lambda s: st)
    c = TestClient(app_module.create_app())
    ov = c.get("/api/billing/overview").json()
    assert ov["configured"] is True and ov["meta"]["retailer"] == "AGL"
    assert "net.period_cost" in ov and ov["period_days"] is not None

    st.record_billing_period(gateway_id=None, retailer="AGL", network="Ausgrid",
                             tariff_name="Flat 30c", period_start=1.0, period_end=2.0,
                             import_kwh=10, import_cost=3.0, net_total=3.0)
    hist = c.get("/api/billing/history").json()
    assert len(hist["periods"]) == 1 and hist["periods"][0]["retailer"] == "AGL"
    csv = c.get("/api/billing/history?fmt=csv")
    assert "text/csv" in csv.headers["content-type"]
    assert csv.text.splitlines()[0].startswith("period_start,period_end,retailer")


def test_overview_unconfigured_without_tariff(tmp_path, monkeypatch):
    st = MetricsStore(str(tmp_path / "m.db"))   # no site/meter/tariff
    monkeypatch.setattr(environment, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "_settings", None)
    monkeypatch.setattr(db, "get_store", lambda s: st)
    c = TestClient(app_module.create_app())
    assert c.get("/api/billing/overview").json()["configured"] is False
