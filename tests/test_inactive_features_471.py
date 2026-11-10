"""#471 — scheduler pickers grey out values and templates whose feature is off, not set up
or in error, with the reason. A value whose feature works but has no reading right now
stays selectable. Existing schedules are never changed; their rows warn instead."""
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from franklinwh_direct_connect_bridge import battery_control
from franklinwh_direct_connect_bridge import scheduler as sch
from franklinwh_direct_connect_bridge.db import MetricsStore

ROOT = Path(__file__).resolve().parents[1] / "src/franklinwh_direct_connect_bridge"


def _settings(**kw):
    base = dict(pv_latitude=None, pv_longitude=None, nem_region="",
                tariff_price_entity="", tariff_feedin_entity="")
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.fixture
def store(tmp_path):
    return MetricsStore(str(tmp_path / "t.db"))


@pytest.fixture
def modbus_on(monkeypatch):
    monkeypatch.setattr(battery_control, "available", lambda: (True, ""))


# ── each value knows its source ──────────────────────────────────────────────
def test_every_catalogue_value_records_its_feature():
    for sid in sch.known_sensor_ids():
        assert sch.sensor_feature(sid) in sch.FEATURES, sid
    assert sch.sensor_feature("battery.soc_pct") == "gateway"
    assert sch.sensor_feature("solar_forecast.today_kwh") == "solar_forecast"
    assert sch.sensor_feature("weather.temp_c") == "solar_forecast"
    assert sch.sensor_feature("solar_forecast.day_pct") == "solar_forecast"
    assert sch.sensor_feature("solar.today_kwh") == "gateway"
    assert sch.sensor_feature("tariff.spot_price") == "spot_price"
    assert sch.sensor_feature("tariff.feed_in_price") == "feed_in_price"
    assert sch.sensor_feature("tariff.buy_rate") == "tariff"
    assert sch.sensor_feature("demand.peak_kw") == "tariff"
    assert sch.sensor_feature("fixed.remaining") == "tariff"
    assert sch.sensor_feature("service.export_allowed") == "utility"
    assert sch.sensor_feature("const.min_discharge_soc") == "constants"
    assert sch.sensor_feature("ha:i1:sensor.x") == "ha:i1"


# ── feature states ───────────────────────────────────────────────────────────
def test_nothing_set_up(store, monkeypatch):
    monkeypatch.setattr(battery_control, "available",
                        lambda: (False, "This bridge's Modbus client is off (Control → Modbus client)"))
    f = sch.feature_states(_settings(), store)
    assert f["gateway"]["state"] == "active"
    assert f["modbus"]["state"] == "off"
    assert "Modbus client off" in f["modbus"]["reason"]
    assert f["solar_forecast"]["state"] == "not_set_up"
    assert "location" in f["solar_forecast"]["reason"]
    assert f["spot_price"]["state"] == "not_set_up"
    assert f["feed_in_price"]["state"] == "not_set_up"
    assert f["tariff"]["state"] == "not_set_up"
    assert f["utility"]["state"] == "not_set_up"


def test_modbus_library_missing_is_an_error(store, monkeypatch):
    monkeypatch.setattr(battery_control, "available",
                        lambda: (False, "franklinwh-modbus library not installed (ImportError)"))
    f = sch.feature_states(_settings(), store)
    assert f["modbus"]["state"] == "error"
    assert "not installed" in f["modbus"]["reason"]


def test_everything_set_up(store, modbus_on):
    store.create_site(sid="s1", name="Home")
    store.create_utility(uid="u1", name="Grid co")
    store.create_tariff(tid="t1", utility_id="u1", name="Flat")
    store.create_meter(mid="m1", site_id="s1", utility_id="u1", tariff_id="t1",
                       is_default=True)
    store.create_ha_instance(ha_id="i1", name="HA Live", base_url="http://x", token="t")
    f = sch.feature_states(_settings(pv_latitude=-33.9, pv_longitude=151.2, nem_region="NSW1",
                                     tariff_feedin_entity="ha:i1:sensor.feedin"), store)
    for k in ("gateway", "modbus", "solar_forecast", "spot_price", "feed_in_price",
              "tariff", "utility", "ha:i1"):
        assert f[k]["state"] == "active", (k, f[k])


def test_spot_price_from_an_ha_entity_only(store, modbus_on):
    store.create_ha_instance(ha_id="i1", name="HA Live", base_url="http://x", token="t")
    f = sch.feature_states(_settings(tariff_price_entity="ha:i1:sensor.amber"), store)
    assert f["spot_price"]["state"] == "active"


def test_price_entity_on_a_disabled_ha_instance_is_off(store, modbus_on):
    store.create_ha_instance(ha_id="i1", name="HA Live", base_url="http://x", token="t",
                             enabled=False)
    f = sch.feature_states(_settings(tariff_price_entity="ha:i1:sensor.amber"), store)
    assert f["spot_price"]["state"] == "off"
    assert "HA Live" in f["spot_price"]["reason"]


def test_disabled_ha_instance_is_off(store, modbus_on):
    store.create_ha_instance(ha_id="i1", name="HA Live", base_url="http://x", token="t",
                             enabled=False)
    f = sch.feature_states(_settings(), store)
    assert f["ha:i1"]["state"] == "off"
    assert "HA Live" in f["ha:i1"]["reason"]


def test_inactive_text_for_a_value():
    f = {"solar_forecast": {"state": "not_set_up", "reason": "set your location"},
         "gateway": {"state": "active", "reason": ""}}
    assert sch.sensor_inactive("solar_forecast.today_kwh", f) == "not set up: set your location"
    assert sch.sensor_inactive("battery.soc_pct", f) is None
    # A feature the bridge doesn't know (an HA instance since deleted) is not set up.
    assert sch.sensor_inactive("ha:gone:sensor.x", f).startswith("not set up")


# ── templates ────────────────────────────────────────────────────────────────
def test_template_needs_its_conditions_features_and_modbus():
    t = next(p for p in sch.PRESETS if p["id"] == "spot_low_charge_ask")
    need = sch.template_features(t)
    assert "modbus" in need and "spot_price" in need
    plain = next(p for p in sch.PRESETS if p["id"] == "self_consumption")
    assert sch.template_features(plain) == []


def test_template_inactive_reason():
    f = {k: {"state": "active", "reason": ""} for k in sch.FEATURES}
    f["modbus"] = {"state": "off", "reason": "Modbus client off"}
    peak = next(p for p in sch.PRESETS if p["id"] == "peak_shave")
    assert sch.template_inactive(peak, f) == "inactive: Modbus client off"
    plain = next(p for p in sch.PRESETS if p["id"] == "self_consumption")
    assert sch.template_inactive(plain, f) is None


# ── API ──────────────────────────────────────────────────────────────────────
@pytest.fixture
def client(tmp_path, monkeypatch, store):
    from fastapi.testclient import TestClient
    from franklinwh_direct_connect_bridge import app as app_module, config, environment, db
    monkeypatch.setattr(environment, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "_settings", None)
    monkeypatch.setattr(db, "get_store", lambda s: store)
    monkeypatch.setattr(battery_control, "available",
                        lambda: (False, "This bridge's Modbus client is off (Control → Modbus client)"))
    return TestClient(app_module.create_app())


def test_api_sensors_carry_their_inactive_reason(client):
    rows = {s["id"]: s for s in client.get("/api/schedules").json()["sensors"]}
    assert rows["battery.soc_pct"]["inactive"] is None
    assert rows["solar_forecast.today_kwh"]["inactive"].startswith("not set up")
    assert rows["tariff.buy_rate"]["inactive"].startswith("not set up")
    assert rows["const.min_discharge_soc"]["inactive"] is None


def test_api_presets_carry_their_inactive_reason(client):
    rows = {p["id"]: p for p in client.get("/api/schedules/presets").json()["presets"]}
    assert rows["peak_shave"]["inactive"].startswith("inactive: ")
    assert rows["self_consumption"]["inactive"] is None
    # The module-level catalogue itself is never mutated.
    assert "inactive" not in next(p for p in sch.PRESETS if p["id"] == "peak_shave")


# ── UI ───────────────────────────────────────────────────────────────────────
def _html():
    return (ROOT / "templates/tabs/scheduler.html").read_text()


def _js():
    return (ROOT / "static/js/scheduler_tab.js").read_text()


def test_picker_rows_are_disabled_with_the_reason():
    html = _html()
    rows = re.findall(r'<template x-for="it in pickerItems\(q\)".*?</template>', html, re.S)
    assert len(rows) >= 6
    for r in rows:
        assert ':disabled="!!it.inactive"' in r, r[:200]
        assert "it.inactive" in r and "'(' + it.inactive + ')'" in r, r[:200]
    assert "inactive: x.inactive" in _js()


def test_variable_picker_rows_are_disabled_with_the_reason():
    html = _html()
    var = html[html.index('data-testid="var-row"') - 400: html.index('data-testid="var-row"') + 900]
    assert ':disabled="!!it.inactive"' in var
    assert "'(' + it.inactive + ')'" in var


def test_template_use_button_is_disabled_with_the_reason():
    html = _html()
    block = html[html.index('x-for="p in presets"'):]
    block = block[:block.index("</template>")]
    assert ':disabled="!!p.inactive"' in block
    assert 'x-text="\'(\' + p.inactive + \')\'"' in block


def test_condition_rows_warn_when_their_feature_is_off():
    js = _js()
    assert "condFeatureWarning(" in js
    html = _html()
    assert 'x-text="condFeatureWarning(item.node)"' in html
    assert "this condition can't be met" in js
