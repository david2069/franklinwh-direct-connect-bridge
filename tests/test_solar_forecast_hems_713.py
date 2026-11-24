"""#713 step 2 (owner 2026-11-17): the solar forecast's maths come from hems (the shared
engine, #612): ``hems.forecast.solar`` with the cell-temperature loss, the Open-Meteo request
and parsing from ``hems.adapters.open_meteo``, and self-calibration against the solar the
gateway measured. The forecast's shape and the scheduler's sensor names are unchanged."""
import pathlib

import pytest

from franklinwh_direct_connect_bridge import scheduler, solar_forecast
from franklinwh_direct_connect_bridge.db import MetricsStore

PKG = pathlib.Path(__file__).resolve().parents[1] / "src" / "franklinwh_direct_connect_bridge"
OFF = 11 * 3600


def raw(day="2026-11-17", gti=None, temp=25.0):
    """An Open-Meteo reply as timezone=auto gives it: location-local times."""
    gti = gti or [0] * 6 + [100, 300, 500, 700, 850, 900, 900, 850, 700, 500, 300, 100] + [0] * 6
    times = [f"{day}T{h:02d}:00" for h in range(24)] + [f"2026-11-18T{h:02d}:00" for h in range(24)]
    return {"utc_offset_seconds": OFF, "timezone": "Australia/Sydney",
            "current": {"temperature_2m": 21.0, "weather_code": 1},
            "hourly": {"time": times, "global_tilted_irradiance": gti + gti,
                       "temperature_2m": [temp] * 48}}


def test_the_hourly_kw_are_hems_with_its_temperature_loss():
    import hems.forecast as hf
    from hems.adapters import open_meteo
    r = raw()
    fc = solar_forecast._compute(r, 5.0)
    want = hf.solar(open_meteo.parse_hourly(r), 5.0, derate=solar_forecast.PV_EFFICIENCY)
    assert [h["kw"] for h in fc["hourly"]] == [w["kw"] for w in want]
    # hot cells lose output: lower than the old GTI × kWp × derate
    noon = fc["hourly"][12]
    assert noon["kw"] < 900 / 1000 * 5.0 * solar_forecast.PV_EFFICIENCY
    # same shape as before: local time strings, daily totals, sensors by the same names
    assert noon["time"] == "2026-11-17T12:00" and noon["temp_c"] == 25.0
    assert fc["days"][0]["date"] == "2026-11-17" and fc["days"][0]["total_kwh"] > 0
    assert set(solar_forecast.sensors(fc)) == {
        "weather.temp_c", "weather.condition", "weather.code", "solar_forecast.today_kwh",
        "solar_forecast.today_peak_kw", "solar_forecast.remaining_kwh",
        "solar_forecast.tomorrow_kwh"}


def test_the_request_is_the_hems_adapter_plus_current_weather(monkeypatch):
    from hems.adapters import open_meteo
    seen = {}
    monkeypatch.setattr(open_meteo, "fetch", lambda url, params, **k: seen.update(url=url, **params) or raw())
    solar_forecast._cache.clear()
    solar_forecast.forecast(-33.8, 151.2, kwp=5.0, tilt=20, azimuth=0, force=True)
    assert seen["url"] == open_meteo.FORECAST_URL
    assert seen["hourly"] == open_meteo.HOURLY and seen["tilt"] == 20 and seen["azimuth"] == 0
    assert seen["current"] == "temperature_2m,weather_code" and seen["timezone"] == "auto"


def test_calibration_learns_from_measured_days_and_scales_the_forecast(tmp_path):
    store = MetricsStore(str(tmp_path / "m.db"))
    key = "k"
    assert solar_forecast.calibration(store, key) == 1.0
    # five days where the gateway measured 80 % of the uncalibrated forecast
    for d in range(10, 16):
        day = f"2026-11-{d:02d}"
        solar_forecast.observe(store, key, day=day, gateway_id="g1", predicted_kwh=20.0,
                               measured_kwh=8.0)
        solar_forecast.observe(store, key, day=day, gateway_id="g2", predicted_kwh=20.0,
                               measured_kwh=8.0)      # a site's gateways add up
    solar_forecast.observe(store, key, day="2026-11-16", gateway_id="g1", predicted_kwh=20.0,
                           measured_kwh=1.0)          # rolls 11-15 into the calibration
    assert solar_forecast.calibration(store, key) == pytest.approx(0.8)
    a = solar_forecast._compute(raw(), 5.0)
    b = solar_forecast._compute(raw(), 5.0, calibration=0.8)
    assert b["hourly"][12]["kw"] == pytest.approx(a["hourly"][12]["kw"] * 0.8, abs=0.002)
    # the uncalibrated day total is kept, so calibration never feeds on itself
    assert b["days"][0]["raw_total_kwh"] == a["days"][0]["total_kwh"]


def test_the_tick_feeds_the_calibration_from_the_gateways_solar_today(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from franklinwh_direct_connect_bridge import state
    store = MetricsStore(str(tmp_path / "m.db"))
    state.reset_gateways()
    gw = state.register_gateway("g1", "192.0.2.10", "g1")
    gw.last_summary = {"ok": True, "power": {"kwh_sun": 12.5}}
    got = []
    monkeypatch.setattr(solar_forecast, "forecast", lambda *a, **k: {
        "utc_offset_seconds": OFF, "days": [{"date": "2026-11-17", "raw_total_kwh": 20.0}],
        "hourly": [], "current": {}})
    monkeypatch.setattr(solar_forecast, "observe", lambda st, key, **k: got.append(k))
    s = SimpleNamespace(pv_latitude=-33.8, pv_longitude=151.2, pv_kwp=5.0, pv_tilt=20,
                        pv_azimuth=0)
    scheduler.solar_snapshot(s, store, "g1", tick=True, now_ts=1794870000)   # 2026-11-17 10:00 AEDT
    assert got == [{"day": "2026-11-17", "gateway_id": "g1", "predicted_kwh": 20.0,
                    "measured_kwh": 12.5}]
    got.clear()
    scheduler.solar_snapshot(s, store, "g1")          # Test / Evaluate: read only
    assert got == []
    state.reset_gateways()


def test_the_pin_is_hems_030():
    txt = (PKG.parents[1] / "pyproject.toml").read_text()
    assert '"hems==0.3.0"' in txt
