"""Derived battery sensors (FEAT-SCHED-ENTRY-PARITY) — computed from live points +
user constants (capacity + SoC targets). Ported from the Modbus bridge; fail-closed."""
from franklinwh_local_bridge import scheduler as sch


def _snap(**kw):
    base = {"battery.soc_pct": None, "battery.power_w": None,
            "const.battery_capacity_kwh": None, "const.max_charge_soc": 100.0,
            "const.min_discharge_soc": 20.0}
    base.update(kw)
    return base


def test_status_from_power_sign():
    assert sch.derived_snapshot(_snap(**{"battery.power_w": -1500}))["battery.status"] == "charging"
    assert sch.derived_snapshot(_snap(**{"battery.power_w": 1500}))["battery.status"] == "discharging"
    assert sch.derived_snapshot(_snap(**{"battery.power_w": 0}))["battery.status"] == "standby"
    # no power reading → no status key
    assert "battery.status" not in sch.derived_snapshot(_snap())


def test_capacity_stored_headroom():
    d = sch.derived_snapshot(_snap(**{"battery.soc_pct": 50, "const.battery_capacity_kwh": 27.2}))
    assert d["battery.capacity_kwh"] == 27.2
    assert d["battery.stored_kwh"] == 13.6            # 27.2 * 0.5
    assert d["battery.remaining_kwh"] == 13.6         # 27.2 - 13.6


def test_capacity_unset_is_none():
    d = sch.derived_snapshot(_snap(**{"battery.soc_pct": 50, "const.battery_capacity_kwh": 0}))
    assert d["battery.capacity_kwh"] is None
    assert d["battery.stored_kwh"] is None and d["battery.remaining_kwh"] is None
    assert d["battery.time_to_charge_now_min"] is None


def test_eta_at_current_rate():
    # 27.2 kWh, SoC 50% → stored 13.6; charging at 2.72 kW toward 100% (27.2 kWh).
    # delta 13.6 kWh / 2.72 kW = 5 h = 300 min.
    d = sch.derived_snapshot(_snap(**{"battery.soc_pct": 50, "const.battery_capacity_kwh": 27.2,
                                      "battery.power_w": -2720, "const.max_charge_soc": 100}))
    assert d["battery.time_to_charge_now_min"] == 300.0
    # discharging toward 20% (5.44 kWh): delta 13.6-5.44=8.16 kWh / 2.72 kW = 180 min.
    d2 = sch.derived_snapshot(_snap(**{"battery.soc_pct": 50, "const.battery_capacity_kwh": 27.2,
                                       "battery.power_w": 2720, "const.min_discharge_soc": 20}))
    assert d2["battery.time_to_discharge_now_min"] == 180.0
    # charging but asked for discharge ETA → not moving toward it → None
    assert d["battery.time_to_discharge_now_min"] is None


def test_eta_already_past_target_is_zero():
    # SoC 95%, charging, target max-charge 90% → already past → 0.0
    d = sch.derived_snapshot(_snap(**{"battery.soc_pct": 95, "const.battery_capacity_kwh": 27.2,
                                      "battery.power_w": -1000, "const.max_charge_soc": 90}))
    assert d["battery.time_to_charge_now_min"] == 0.0


def test_derived_group_and_live_evaluate(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from franklinwh_local_bridge import app as app_module, config, environment, db
    from franklinwh_local_bridge.db import MetricsStore
    st = MetricsStore(str(tmp_path / "m.db"))
    monkeypatch.setattr(environment, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "_settings", None)
    monkeypatch.setattr(db, "get_store", lambda s: st)
    c = TestClient(app_module.create_app())
    # capacity set → derived sensors become computable
    c.put("/api/constants", json={"battery_capacity_kwh": 27.2})
    sensors = {s["id"]: s["group"] for s in c.get("/api/schedules").json()["sensors"]}
    assert sensors.get("battery.stored_kwh") == "Derived Battery"
    assert sensors.get("battery.time_to_discharge_now_min") == "Derived Battery"


def test_eta_at_max_rate_constant_fallback():
    # 27.2 kWh, SoC 50% → stored 13.6; max-power fallback 5 kW → charge to 100% (27.2 kWh):
    # delta 13.6 / 5 kW = 2.72 h = 163.2 min.
    d = _snap(**{"battery.soc_pct": 50, "const.battery_capacity_kwh": 27.2,
                 "const.battery_max_power_kw": 5.0, "const.max_charge_soc": 100,
                 "const.min_discharge_soc": 20})
    out = __import__("franklinwh_local_bridge.scheduler", fromlist=["scheduler"]).derived_snapshot(d)
    assert out["battery.time_to_charge_min"] == 163.2
    # discharge to 20% (5.44 kWh): delta 8.16 / 5 kW = 97.9 min
    assert out["battery.time_to_discharge_min"] == 97.9


def test_eta_at_max_rate_prefers_modbus_ratings():
    from franklinwh_local_bridge import scheduler as sch
    d = _snap(**{"battery.soc_pct": 50, "const.battery_capacity_kwh": 27.2,
                 "const.battery_max_power_kw": 5.0, "const.max_charge_soc": 100,
                 "ratings.max_charge_w": 8000})   # Modbus says 8 kW → overrides the 5 kW constant
    out = sch.derived_snapshot(d)
    # delta 13.6 / 8 kW = 1.7 h = 102 min
    assert out["battery.time_to_charge_min"] == 102.0


def test_solar_tracker_pct_derived():
    """solar_forecast.day_pct + vs_expected_pct from actual (kwh_sun) vs the forecast."""
    from franklinwh_local_bridge import scheduler
    snap = {
        "solar.today_kwh": 10.0,                # actual so far
        "solar_forecast.today_kwh": 40.0,       # full-day forecast
        "solar_forecast.remaining_kwh": 30.0,   # expected-to-now = 40 - 30 = 10
    }
    out = scheduler.derived_snapshot(snap)
    assert out["solar_forecast.day_pct"] == 25.0             # 10/40
    assert out["solar_forecast.vs_expected_pct"] == 100.0    # 10/10 -> on track
    # ahead case
    out2 = scheduler.derived_snapshot({**snap, "solar.today_kwh": 12.0})
    assert out2["solar_forecast.vs_expected_pct"] == 120.0   # 12/10 -> 20% ahead
    # missing forecast -> sensors absent (not a crash)
    out3 = scheduler.derived_snapshot({"solar.today_kwh": 5.0})
    assert "solar_forecast.day_pct" not in out3
