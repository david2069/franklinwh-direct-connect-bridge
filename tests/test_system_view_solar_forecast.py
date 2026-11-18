"""System view: Solar forecast & actual (owner 2026-11-19, franklinwh-system-view 0.5.0).
Each gateway sends today's forecast and what is still to come, from its site's solar
forecast (the Solar tab's, calibrated), and the solar made so far from its summary. The
forecast is read from the cache only (a stale one refreshes in the background), so the view
never waits on Open-Meteo; a gateway whose site has no forecast sends none."""
import datetime as dt
from types import SimpleNamespace

import pytest

import franklinwh_system_view as sv
from franklinwh_direct_connect_bridge import db, site_location, solar_forecast, state, system_view

from test_system_view_428 import gw, us_summary

LOC = {"latitude": -33.9, "longitude": 151.2, "pv_tilt": 20.0, "pv_azimuth": 0.0, "kwp": 6.6}
CFG = SimpleNamespace(pv_latitude=None, pv_longitude=None)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    state.reset_gateways()
    monkeypatch.setattr(db, "get_store", lambda cfg: (_ for _ in ()).throw(RuntimeError("no db")))
    monkeypatch.setattr(solar_forecast, "_cache", {})
    yield
    state.reset_gateways()


def _fc():
    today = dt.date.today().isoformat()
    return {"current": {}, "utc_offset_seconds": 0,
            "days": [{"date": today, "total_kwh": 28.6, "peak_kw": 4.1}],
            "hourly": [{"time": today + "T23:59", "kw": 0.0}]}


def test_a_gateway_sends_its_sites_forecast_and_the_actual(monkeypatch):
    monkeypatch.setattr(site_location, "for_gateway", lambda s, st, gid, **k: LOC)
    key = solar_forecast.site_key(LOC["latitude"], LOC["longitude"], LOC["pv_tilt"], LOC["pv_azimuth"], LOC["kwp"])
    import time
    solar_forecast._cache[key] = (time.time(), _fc())
    summ = us_summary(solar_w=3100.0)
    summ["energy_today"] = {"solar": 21.4}
    gw(summary=summ)
    p = system_view.raw_payload(CFG)
    sf = p["gateways"][0]["solar_forecast"]
    assert sf["forecast_kwh"] == 28.6 and sf["actual_kwh"] == 21.4 and sf["remaining_kwh"] == 0.0
    assert sv.validate(p) == []
    assert sv.build(p)["gateways"][0]["solar_today"]["rows"][0] == ["Forecast", "28.6 kWh"]


def test_no_forecast_means_none_and_the_request_never_waits(monkeypatch):
    calls = []
    monkeypatch.setattr(solar_forecast, "forecast", lambda *a, **k: calls.append(1) or _fc())
    monkeypatch.setattr(system_view.threading, "Thread",
                        lambda target, **k: SimpleNamespace(start=lambda: calls.append("bg")))
    monkeypatch.setattr(site_location, "for_gateway", lambda s, st, gid, **k: LOC)
    gw(summary=us_summary())
    p = system_view.raw_payload(CFG)
    assert "solar_forecast" not in p["gateways"][0]      # nothing cached yet: left out
    assert calls == ["bg"]                               # fetched in the background, not inline
    # a site without a location or PV size: no forecast at all
    monkeypatch.setattr(site_location, "for_gateway", lambda s, st, gid, **k: {**LOC, "latitude": None})
    calls.clear()
    assert "solar_forecast" not in system_view.raw_payload(CFG)["gateways"][0] and calls == []


def test_the_pin_has_the_option():
    assert tuple(int(x) for x in sv.__version__.split(".")[:2]) >= (0, 5)
