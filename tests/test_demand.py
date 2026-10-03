"""Billing Phases 2-3 — BillingTracker (power-integration): demand, energy cost,
bonus + export charge. Fed synthetic (grid_w, now) samples; prices via rate_model."""
import datetime as dt
from franklinwh_local_bridge import billing
from franklinwh_local_bridge.db import MetricsStore

DAY = {"start": "00:00", "end": "24:00"}            # explicit all-day window
CFG = {"pricing": {}, "cycle_day": 1, "bonus": None, "charge": None,
       "demand": {"window": DAY, "rate": 10.0, "interval_min": 30, "charge_basis": "per_kw_day"}}


def test_period_start_boundary():
    now = dt.datetime(2026, 9, 20, 12, 0)
    assert billing._period_start(now, 1) == dt.datetime(2026, 9, 1)
    assert billing._period_start(now, 25) == dt.datetime(2026, 8, 25)
    assert billing._period_start(dt.datetime(2026, 3, 31), 31) == dt.datetime(2026, 3, 31)


# ── Phase 2: demand ──
def test_demand_as_points_math():
    tr = billing.BillingTracker()
    tr._s.update({"period_start": dt.datetime(2026, 9, 1).timestamp(), "peak_kwh": 1.5})
    pts = tr.as_points(CFG, dt.datetime(2026, 9, 11))
    assert pts["demand.peak_kw"] == 3.0 and pts["demand.period_charge"] == 300.0
    flat = {**CFG, "demand": {**CFG["demand"], "charge_basis": "flat_per_kw"}}
    assert tr.as_points(flat, dt.datetime(2026, 9, 11))["demand.period_charge"] == 30.0


def test_demand_interval_close_folds_peak():
    tr = billing.BillingTracker()
    base = dt.datetime(2026, 9, 15, 10, 0, 0)
    tr.update(None, "g", 3600, CFG, base)
    tr.update(None, "g", 3600, CFG, base + dt.timedelta(minutes=10))
    tr.update(None, "g", 3600, CFG, base + dt.timedelta(minutes=20))
    tr.update(None, "g", 3600, CFG, base + dt.timedelta(minutes=35))
    assert tr.as_points(CFG, base + dt.timedelta(minutes=35))["demand.peak_kw"] == 2.4


def test_demand_out_of_window_not_counted():
    cfg = {**CFG, "demand": {**CFG["demand"], "window": {"start": "15:00", "end": "21:00"}}}
    tr = billing.BillingTracker()
    base = dt.datetime(2026, 9, 15, 10, 0, 0)
    for mins in (0, 10, 35):
        tr.update(None, "g", 5000, cfg, base + dt.timedelta(minutes=mins))
    assert tr.as_points(cfg, base + dt.timedelta(minutes=35))["demand.peak_kw"] == 0.0


def test_period_rollover_resets():
    tr = billing.BillingTracker()
    tr._s.update({"period_start": dt.datetime(2026, 8, 1).timestamp(), "peak_kwh": 5.0,
                  "import_cost": 9.0})
    tr.update(None, "g", 1000, CFG, dt.datetime(2026, 9, 2, 0, 0))
    assert tr._s["peak_kwh"] == 0.0 and tr._s["import_cost"] == 0.0


# ── Phase 3: energy cost ──
def test_energy_import_cost_and_export_credit():
    cfg = {**CFG, "pricing": {"default_rate": {"buy": 0.30, "sell": 0.08}}, "demand": None}
    tr = billing.BillingTracker()
    base = dt.datetime(2026, 9, 15, 10, 0, 0)
    tr.update(None, "g", 3600, cfg, base)                                   # first (no dt)
    tr.update(None, "g", 3600, cfg, base + dt.timedelta(minutes=30))        # +1.8 kWh import
    tr.update(None, "g", -3600, cfg, base + dt.timedelta(minutes=60))       # +1.8 kWh export
    pts = tr.as_points(cfg, base + dt.timedelta(minutes=60))
    assert pts["energy.period_import_kwh"] == 1.8
    assert pts["energy.import_cost"] == round(1.8 * 0.30, 4)               # 0.54
    assert pts["energy.export_credit"] == round(1.8 * 0.08, 4)            # 0.144
    assert "demand.peak_kw" not in pts                                     # no demand window


def test_energy_unpriced_when_no_rate():
    cfg = {**CFG, "pricing": {}, "demand": None}                           # no rate at all
    tr = billing.BillingTracker()
    base = dt.datetime(2026, 9, 15, 10, 0, 0)
    tr.update(None, "g", 3600, cfg, base)
    tr.update(None, "g", 3600, cfg, base + dt.timedelta(minutes=30))
    pts = tr.as_points(cfg, base + dt.timedelta(minutes=30))
    assert pts["energy.unpriced_import_kwh"] == 1.8 and pts["energy.import_cost"] == 0.0


# ── Phase 3: bonus + export charge ──
def test_bonus_export_credit():
    cfg = {**CFG, "pricing": {"default_rate": {"buy": 0.3}}, "demand": None,
           "bonus": {"window": {"start": "17:00", "end": "21:00"}, "rate": 0.28}}
    tr = billing.BillingTracker()
    base = dt.datetime(2026, 9, 15, 18, 0, 0)                              # inside bonus window
    tr.update(None, "g", -3600, cfg, base)
    tr.update(None, "g", -3600, cfg, base + dt.timedelta(minutes=30))     # +1.8 kWh export in window
    pts = tr.as_points(cfg, base + dt.timedelta(minutes=30))
    assert pts["bonus.export_kwh"] == 1.8
    assert pts["bonus.period_credit"] == round(1.8 * 0.28, 2)            # 0.50


def test_export_charge_free_and_net():
    cfg = {**CFG, "pricing": {"default_rate": {"sell": 0.05}}, "demand": None,
           "charge": {"window": DAY, "rate": 0.10, "free_kwh_per_day": 5.0}}
    tr = billing.BillingTracker()
    tr._s.update({"period_start": dt.datetime(2026, 9, 1).timestamp(),
                  "charge_export_wh": 200_000.0})                          # 200 kWh exported in window
    now = dt.datetime(2026, 9, 30)                                         # ~29 days in
    pts = tr.as_points(cfg, now)
    # free allowance = 5 kWh/day × 30-day period = 150 kWh; net = 200 - 150 = 50; cost = 50 × 0.10
    assert pts["tariff.export_charge_kwh"] == 200.0
    assert pts["tariff.export_charge_net_kwh"] == 50.0
    assert pts["tariff.export_charge_free_remaining"] == 0.0
    assert pts["tariff.export_charge_cost"] == 5.0


def test_billing_tick_end_to_end(tmp_path):
    st = MetricsStore(str(tmp_path / "m.db"))
    st.ensure_default_site_meter()
    st.create_utility(uid="u1", name="AGL")
    st.create_tariff(tid="t1", utility_id="u1", name="TOU",
                     pricing={"default_rate": {"buy": 0.3, "sell": 0.08}}, billing_cycle_day=1)
    m = next(x for x in st.meters() if x.get("is_default"))
    st.update_meter(m["id"], tariff_id="t1")
    billing._TRACKERS.clear()
    out = billing.billing_tick(st, None, 4000, dt.datetime(2026, 9, 15, 10, 0))
    # a flat tariff (no demand/bonus/charge windows) → energy.* only
    assert "energy.period_import_kwh" in out
    assert "demand.peak_kw" not in out and "bonus.export_kwh" not in out


def test_billing_tick_empty_without_tariff(tmp_path):
    st = MetricsStore(str(tmp_path / "m.db"))
    st.ensure_default_site_meter()
    billing._TRACKERS.clear()
    assert billing.billing_tick(st, None, 4000, dt.datetime(2026, 9, 15, 10, 0)) == {}


# ── Phase 4: fixed charges (deterministic accrual) ──
def _store_with_fixed(tmp_path, charges):
    st = MetricsStore(str(tmp_path / "m.db"))
    st.ensure_default_site_meter()
    st.create_utility(uid="u1", name="AGL")
    st.create_tariff(tid="t1", utility_id="u1", name="TOU",
                     pricing={"default_rate": {"buy": 0.3}}, fixed_charges=charges, billing_cycle_day=1)
    m = next(x for x in st.meters() if x.get("is_default"))
    st.update_meter(m["id"], tariff_id="t1")
    return st


def test_fixed_accrual_daily_and_monthly(tmp_path):
    st = _store_with_fixed(tmp_path, [{"frequency": "daily", "rate": 1.0},
                                      {"frequency": "monthly", "rate": 30.0}])
    now = dt.datetime(2026, 9, 11)                    # 10 days into a 30-day Sep period
    pts = billing.fixed_snapshot(st, None, now)
    assert pts["fixed.daily_charge"] == 2.0          # $1/day + $30/30-days
    assert pts["fixed.accrued_period"] == 20.0       # 2 × 10
    assert pts["fixed.period_total"] == 60.0         # 2 × 30
    assert pts["fixed.remaining"] == 40.0
    assert pts["fixed.days_remaining"] == 20.0


def test_fixed_tax_inclusive(tmp_path):
    st = _store_with_fixed(tmp_path, [{"frequency": "daily", "rate": 1.0, "tax_rate": 0.10}])
    assert billing.fixed_snapshot(st, None, dt.datetime(2026, 9, 5))["fixed.daily_charge"] == 1.1


def test_fixed_empty_without_charges(tmp_path):
    st = _store_with_fixed(tmp_path, [])
    assert billing.fixed_snapshot(st, None, dt.datetime(2026, 9, 5)) == {}


def test_billing_resets_on_tariff_change():
    """Supersede: when the meter's tariff changes mid-period, the numbers accrued so
    far belong to the OLD tariff — the tracker starts fresh under the new one."""
    cfg1 = {**CFG, "pricing": {"default_rate": {"buy": 0.3}}, "demand": None, "tariff_id": "t1"}
    cfg2 = {**cfg1, "tariff_id": "t2"}
    tr = billing.BillingTracker()
    base = dt.datetime(2026, 9, 15, 10, 0, 0)
    tr.update(None, "g", 3600, cfg1, base)
    tr.update(None, "g", 3600, cfg1, base + dt.timedelta(minutes=30))     # accrue under t1
    assert tr._s["period_import_kwh"] > 0 and tr._s["tariff_id"] == "t1"
    tr.update(None, "g", 3600, cfg2, base + dt.timedelta(minutes=40))     # tariff → t2 (supersede)
    assert tr._s["period_import_kwh"] == 0.0 and tr._s["tariff_id"] == "t2"


def test_tariff_effective_dates_round_trip(tmp_path):
    st = MetricsStore(str(tmp_path / "m.db"))
    st.create_utility(uid="u1", name="AGL")
    t = st.create_tariff(tid="t1", utility_id="u1", name="Old plan",
                         effective_start="2026-01-01", effective_end="2026-06-30")
    assert t["effective_start"] == "2026-01-01" and t["effective_end"] == "2026-06-30"
    st.update_tariff("t1", effective_end="2026-12-31")
    assert st.tariff("t1")["effective_end"] == "2026-12-31"
