"""#428: the System view's site name and weather, and the Customise diagram answers.

The weather is the solar page's cached Open-Meteo forecast; a request never waits on it.
Customise answers are bridge settings in DATA_DIR; saving them sends nothing to an aGate.
"""
import threading
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import app as app_module
from franklinwh_direct_connect_bridge import client as client_module
from franklinwh_direct_connect_bridge import environment, solar_forecast, state, system_view

from test_system_view_428 import us_summary


@pytest.fixture(autouse=True)
def _clean(tmp_path, monkeypatch):
    monkeypatch.setattr(environment, "DATA_DIR", str(tmp_path))
    solar_forecast._cache.clear()
    state.reset_gateways()
    yield
    state.reset_gateways()
    solar_forecast._cache.clear()


def cfg(lat=-33.87, lon=151.21):
    return SimpleNamespace(pv_latitude=lat, pv_longitude=lon, pv_kwp=5.0, pv_tilt=20.0, pv_azimuth=0.0)


def cache(c, *, age=0.0, tz="Australia/Sydney", code=2):
    key = f"{c.pv_latitude},{c.pv_longitude},{c.pv_tilt},{c.pv_azimuth},{c.pv_kwp}"
    solar_forecast._cache[key] = (time.time() - age, {
        "timezone": tz, "current": {"code": code, "condition": "Partly cloudy", "temp_c": 21.4}})


def test_the_site_is_named_from_the_location_and_shows_the_weather(monkeypatch):
    monkeypatch.setattr(solar_forecast, "forecast", lambda *a, **k: pytest.fail("fresh cache: no fetch"))
    c = cfg()
    cache(c)
    s = system_view.site(c)
    assert s["name"] == "Sydney"
    assert s["weather"] == {"code": 2, "condition": "Partly cloudy", "temp_c": 21.4}


def test_a_stale_forecast_refreshes_in_the_background_not_in_the_request(monkeypatch):
    started, release = threading.Event(), threading.Event()

    def slow(*a, **k):
        started.set()
        release.wait(5)
    monkeypatch.setattr(solar_forecast, "forecast", slow)
    c = cfg()
    cache(c, age=solar_forecast.CACHE_S + 1, tz="America/Los_Angeles")
    t0 = time.time()
    assert system_view.site(c)["name"] == "Los Angeles"      # the stale one, at once
    assert time.time() - t0 < 1
    assert started.wait(2)
    release.set()


def test_no_location_means_no_name_no_weather_and_no_fetch(monkeypatch):
    monkeypatch.setattr(solar_forecast, "forecast", lambda *a, **k: pytest.fail("no location: no fetch"))
    assert system_view.site(cfg(lat=None, lon=None)) == {}


def test_the_legs_reading_reaches_the_payload():
    g = state.register_gateway("gw1", "127.0.0.1:9000", "aGate")
    g.last_summary = us_summary()
    assert system_view.gateway_payload(g)["grid"]["legs_v"] == [120.8, 120.8]


def test_customise_saves_in_the_bridge_and_the_diagram_follows(monkeypatch):
    for name in ("summary", "power", "firmware", "device_model"):
        monkeypatch.setattr(client_module, name, lambda *a, **k: pytest.fail("no aGate I/O"), raising=False)
    state.register_gateway("gw1", "127.0.0.1:9000", "aGate").last_summary = us_summary()
    c = TestClient(app_module.create_app())
    body = c.get("/api/system").json()
    assert body["customise"]["endpoint"] == "api/system/customise"
    assert any(f["key"] == "legs" and f["help"] == "Your aGate reads 2 legs." for f in body["customise"]["fields"])
    r = c.put("/api/system/customise", json={"site": {"name": "Beach house"},
                                             "gw1": {"name": "Garage", "circuit1_icon": "hvac", "legs": ""}})
    assert r.status_code == 200 and r.json()["saved"] == {"site": {"name": "Beach house"},
                                                          "gw1": {"name": "Garage", "circuit1_icon": "hvac"}}
    assert system_view.load_saved()["gw1"]["name"] == "Garage"
    body = c.get("/api/system").json()
    g = body["gateways"][0]
    assert body["strip"]["name"] == "Beach house"
    assert g["name"] == "Garage"
    assert {n["id"]: n["icon"] for n in g["scenes"]["landscape"]["nodes"]}["sc1"] == "hvac"


@pytest.mark.parametrize("bad", [{"gw9": {"name": "x"}}, {"gw1": {"legs": "L7"}}, ["x"]])
def test_an_answer_the_form_never_offers_is_refused(bad):
    state.register_gateway("gw1", "127.0.0.1:9000", "aGate").last_summary = us_summary()
    r = TestClient(app_module.create_app()).put("/api/system/customise", json=bad)
    assert r.status_code == 400
    assert system_view.load_saved() == {}


def test_an_unreadable_answers_file_is_no_answers():
    system_view.saved_path().write_text("{not json")
    assert system_view.load_saved() == {}
