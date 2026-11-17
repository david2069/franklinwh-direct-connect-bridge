"""#713 step 3 (owner 2026-11-17): the home-load forecast from hems (fit_load / predict_load)
on the gateway's own hourly history and the site's temperatures, to Home Assistant as a
``Load Forecast`` sensor with HAEO's ``forecast`` attribute, and its walk-forward backtest in
the weekly battery report."""
import datetime as dt
import json
import pathlib
from types import SimpleNamespace

import pytest

from franklinwh_direct_connect_bridge import health_report as hr, load_forecast, setup_wizard
from franklinwh_direct_connect_bridge.db import MetricsStore
from franklinwh_direct_connect_bridge.publish import entities

ROOT = pathlib.Path(__file__).resolve().parents[1]
PKG = ROOT / "src" / "franklinwh_direct_connect_bridge"
TZ = "Australia/Sydney"
NOW = dt.datetime(2026, 11, 17, 10, 20, tzinfo=dt.timezone(dt.timedelta(hours=11))).timestamp()


@pytest.fixture
def st(tmp_path):
    s = MetricsStore(str(tmp_path / "m.db"))
    setup_wizard.set_site_timezone(s, TZ)
    load_forecast._models.clear()
    yield s
    s.close()


def seed(st, days, gw="gw1"):
    """``days`` of polls every 15 min: 400 W at night, 1.2 kW 17:00–21:00, 600 W else."""
    start = int(NOW) // 3600 * 3600 - days * 86400
    for t in range(start, int(NOW), 900):
        h = dt.datetime.fromtimestamp(t, dt.timezone(dt.timedelta(hours=11))).hour
        w = 1200 if 17 <= h < 21 else 400 if h < 6 else 600
        st.insert({"load_w": w, "soc": 50}, t, gateway_id=gw)


def no_fetch(*a, **k):
    raise OSError("offline in tests")


SETTINGS = SimpleNamespace(pv_latitude=None, pv_longitude=None, pv_kwp=None, pv_tilt=20,
                           pv_azimuth=0)


def test_the_hourly_history_is_the_mean_load_per_hour(st):
    seed(st, 2)
    rows = load_forecast.hourly_load(st, "gw1", int(NOW) - 86400, int(NOW))
    assert rows and all(set(r) == {"start", "kwh"} for r in rows)
    evening = [r for r in rows if dt.datetime.fromtimestamp(
        r["start"], dt.timezone(dt.timedelta(hours=11))).hour == 18]
    assert evening[0]["kwh"] == pytest.approx(1.2)


def test_the_ha_payload_is_this_hours_kw_and_haeos_series(st):
    seed(st, 40)
    p = load_forecast.ha_payload(st, SETTINGS, "gw1", NOW, fetch=no_fetch)
    assert p["method"] == "model"
    assert p["kw"] == pytest.approx(0.6, abs=0.05)           # 10:00 is a 600 W hour
    assert len(p["forecast"]) == 2 * load_forecast.HORIZON_H       # every 30 minutes
    assert set(p["forecast"][0]) == {"time", "value"}
    assert p["forecast"][0]["time"].startswith("2026-11-17T10:00")
    evening = [x for x in p["forecast"] if "T18:00" in x["time"]]
    assert evening[0]["value"] == pytest.approx(1.2, abs=0.05)


def test_little_history_falls_back_to_the_cold_start_and_none_gives_nothing(st):
    assert load_forecast.ha_payload(st, SETTINGS, "gw1", NOW, fetch=no_fetch) is None
    seed(st, 10)
    # still degraded: refitted the next hour, not the next day
    p = load_forecast.ha_payload(st, SETTINGS, "gw1", NOW + 3600, fetch=no_fetch)
    assert p["method"] == "cold_start"


def test_the_archive_temperatures_are_fetched_once_a_day_and_kept(st):
    calls = []

    def fetch(url, params, **k):
        calls.append(params)
        t0 = dt.datetime.fromisoformat(params["start_date"])
        times = [(t0 + dt.timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M") for i in range(48)]
        return {"utc_offset_seconds": 0, "hourly": {"time": times,
                                                    "temperature_2m": [20.0] * 48,
                                                    "global_tilted_irradiance": [0] * 48}}
    loc = {"latitude": -33.9, "longitude": 151.2, "pv_tilt": 20, "pv_azimuth": 0}
    tz = load_forecast._zone(st)
    a = load_forecast.archive_temps(st, loc, tz, int(NOW) - 2 * 86400, int(NOW), fetch=fetch)
    b = load_forecast.archive_temps(st, loc, tz, int(NOW) - 2 * 86400, int(NOW), fetch=fetch)
    assert len(calls) == 1 and a == b and set(a.values()) == {20.0}
    assert calls[0]["hourly"] and calls[0]["timezone"] == "GMT"


def test_load_forecast_is_a_ha_sensor_on_its_own_topic_with_the_forecast_attribute():
    e = next(x for x in entities.ENTITIES if x["key"] == "load_forecast")
    assert e["source"] == "local" and e["group"] == "power"
    cfgs, _, _ = entities.discovery_configs("n1", {}, "fwh", "homeassistant")
    cfg = dict(cfgs)["homeassistant/sensor/n1/load_forecast/config"]
    assert cfg["state_topic"] == "fwh/n1/load_forecast" == entities.load_forecast_topic("n1", "fwh")
    assert cfg["unit_of_measurement"] == "kW" and "state_class" not in cfg
    assert "forecast" in cfg["json_attributes_template"]
    assert cfg["json_attributes_topic"] == cfg["state_topic"]


def test_the_publisher_sends_it_retained():
    from franklinwh_direct_connect_bridge.publish.mqtt_publisher import MqttPublisher
    sent = []
    pub = MqttPublisher.__new__(MqttPublisher)
    pub.node, pub.s = "n1", SimpleNamespace(mqtt_prefix="fwh")
    pub.client = SimpleNamespace(publish=lambda t, p, retain=False: sent.append((t, json.loads(p), retain)))
    pub.publish_load_forecast({"kw": 0.6, "forecast": []})
    assert sent == [("fwh/n1/load_forecast", {"kw": 0.6, "forecast": []}, True)]


def test_the_poller_publishes_it_off_the_poll_thread_every_half_hour():
    src = (PKG / "poller.py").read_text()
    assert "LOAD_FORECAST_EVERY_S = 1800" in src
    assert "load_forecast.ha_payload" in src and "pub.publish_load_forecast" in src


def test_the_weekly_report_carries_the_backtest(st, monkeypatch):
    seed(st, 40)
    monkeypatch.setattr(load_forecast, "archive_temps", lambda *a, **k: {})
    g = hr.build_weekly(st, NOW, gateways=[{"id": "gw1", "name": "Home"}])["gateways"][0]
    bt = g["load_forecast"]
    assert bt["days"] > 0 and bt["model"]["daily_mape_pct"] is not None
    assert {"model", "cold_start", "persistence"} <= set(bt)
    html = (PKG / "templates" / "tabs" / "health.html").read_text()
    assert "g.load_forecast" in html and "Load forecast" in html


def test_documented():
    doc = (ROOT / "docs" / "guide" / "home-assistant.md").read_text()
    assert "`load_forecast`" in doc and "HAEO" in doc
