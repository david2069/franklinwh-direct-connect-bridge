"""Generic dynamic-pricing attributes (owner 2026-11-16): price spike and demand window,
plus the forecasts, descriptors and renewables an Amber Electric site publishes, as
scheduler sensors for any price source. A source that has no such value (AEMO NEM,
ComEd …) leaves it None, never NaN. Prices sit with billing too (#582)."""
import pathlib
from types import SimpleNamespace

from franklinwh_direct_connect_bridge import dynamic_price, scheduler

PKG = pathlib.Path(__file__).resolve().parents[1] / "src" / "franklinwh_direct_connect_bridge"
INST = "i1"


def st(eid, state, unit=None):
    return {"entity_id": eid, "state": state,
            "attributes": {"unit_of_measurement": unit} if unit else {}}


AMBER = [st("sensor.roseville_general_price", "0.199", "$/kWh"),
         st("sensor.roseville_feed_in_price", "0.123", "$/kWh"),
         st("sensor.roseville_general_forecast", "0.207", "$/kWh"),
         st("sensor.roseville_feed_in_forecast", "0.131", "$/kWh"),
         st("sensor.roseville_general_price_descriptor", "very_low"),
         st("sensor.roseville_feed_in_price_descriptor", "high"),
         st("sensor.roseville_renewables", "13", "%"),
         st("binary_sensor.roseville_price_spike", "off"),
         st("binary_sensor.roseville_demand_window", "on"),
         st("sensor.roseville_temp_max_0", "24")]


def ha(eid):
    return f"ha:{INST}:{eid}"


def settings(**kw):
    base = dict(tariff_price_entity="", tariff_feedin_entity="", nem_region="",
                price_spike_c=0.0, price_spike_entity="", demand_window_entity="",
                tariff_price_forecast_entity="", tariff_feedin_forecast_entity="",
                tariff_price_descriptor_entity="", tariff_feedin_descriptor_entity="",
                tariff_renewables_entity="")
    return SimpleNamespace(**{**base, **kw})


def test_the_attributes_are_one_list_with_a_scheduler_sensor_each():
    keys = [a["sensor"] for a in dynamic_price.ATTRIBUTES]
    for k in ("tariff.spot_price", "tariff.feed_in_price", "tariff.price_forecast",
              "tariff.feed_in_forecast", "tariff.price_descriptor", "tariff.feed_in_descriptor",
              "tariff.renewables_pct", "tariff.price_spike", "tariff.demand_window_active"):
        assert k in keys, k
    ids = {s for s, _ in scheduler.TARIFF_SENSORS}
    assert {"tariff.price_forecast", "tariff.feed_in_forecast", "tariff.price_descriptor",
            "tariff.feed_in_descriptor", "tariff.renewables_pct"} <= ids


def test_amber_electric_siblings_are_found_from_its_price_sensor():
    got = dynamic_price.related(ha("sensor.roseville_general_price"), AMBER)
    assert got == {
        "tariff_price_entity": ha("sensor.roseville_general_price"),
        "tariff_feedin_entity": ha("sensor.roseville_feed_in_price"),
        "tariff_price_forecast_entity": ha("sensor.roseville_general_forecast"),
        "tariff_feedin_forecast_entity": ha("sensor.roseville_feed_in_forecast"),
        "tariff_price_descriptor_entity": ha("sensor.roseville_general_price_descriptor"),
        "tariff_feedin_descriptor_entity": ha("sensor.roseville_feed_in_price_descriptor"),
        "tariff_renewables_entity": ha("sensor.roseville_renewables"),
        "price_spike_entity": ha("binary_sensor.roseville_price_spike"),
        "demand_window_entity": ha("binary_sensor.roseville_demand_window")}
    # only what exists: a site without forecasts gets none
    bare = [s for s in AMBER if "forecast" not in s["entity_id"]]
    assert "tariff_price_forecast_entity" not in dynamic_price.related(
        ha("sensor.roseville_general_price"), bare)
    # any of its sensors names the site, and an unknown sensor finds nothing
    assert dynamic_price.related(ha("sensor.roseville_feed_in_price"), AMBER)["price_spike_entity"]
    assert dynamic_price.related(ha("sensor.comed_price"), AMBER) == {}


def test_the_ha_source_fills_every_attribute_it_has(monkeypatch):
    by_id = {ha(s["entity_id"]): s for s in AMBER}
    monkeypatch.setattr(dynamic_price, "_states", lambda store, ids: {i: by_id[i] for i in ids if i in by_id})
    s = settings(**dynamic_price.related(ha("sensor.roseville_general_price"), AMBER))
    out = scheduler.ha_price_snapshot(s, None)
    assert out["tariff.spot_price"] == 19.9 and out["tariff.feed_in_price"] == 12.3
    assert out["tariff.price_forecast"] == 20.7 and out["tariff.feed_in_forecast"] == 13.1
    assert out["tariff.price_descriptor"] == "very_low" and out["tariff.feed_in_descriptor"] == "high"
    assert out["tariff.renewables_pct"] == 13.0


def test_a_source_without_them_leaves_them_none_not_nan(monkeypatch):
    """AEMO NEM gives a price only: every other attribute is in the snapshot as None."""
    monkeypatch.setattr(scheduler, "nem_snapshot", lambda *a, **k: {"tariff.spot_price": 8.5})
    monkeypatch.setattr(scheduler, "ha_price_snapshot", lambda *a, **k: {})
    snap = {"tariff.spot_price": 8.5}
    dynamic_price.fill_missing(snap)
    for a in dynamic_price.ATTRIBUTES:
        assert a["sensor"] in snap
    assert snap["tariff.spot_price"] == 8.5
    assert snap["tariff.feed_in_price"] is None and snap["tariff.price_descriptor"] is None
    assert all(v is None or v == v for v in snap.values())          # no NaN anywhere
    assert "dynamic_price.fill_missing(snapshot)" in (PKG / "scheduler.py").read_text()


def test_the_new_entities_are_settings():
    from franklinwh_direct_connect_bridge import config
    for k in ("tariff_price_forecast_entity", "tariff_feedin_forecast_entity",
              "tariff_price_descriptor_entity", "tariff_feedin_descriptor_entity",
              "tariff_renewables_entity"):
        assert hasattr(config.Settings(), k) and k in config._OVERRIDE_KEYS, k


def test_prices_are_on_the_billing_page_too_from_one_partial():
    part = (PKG / "templates" / "partials" / "prices.html").read_text()
    assert 'data-testid="prices-section"' in part and 'data-testid="prices-fill-related"' in part
    for f in ("tariff_price_forecast_entity", "tariff_feedin_forecast_entity",
              "tariff_price_descriptor_entity", "tariff_feedin_descriptor_entity",
              "tariff_renewables_entity"):
        assert f in part, f
    for page in ("tabs/settings.html", "tabs/energy_costs.html"):
        assert '{% include "partials/prices.html" %}' in (PKG / "templates" / page).read_text(), page


def test_spike_and_demand_window_work_from_entities_that_are_not_exposed(monkeypatch):
    """The owner's Amber sensors weren't exposed, and price_events looked only at exposed
    entities, so a set spike or demand-window sensor read nothing."""
    by_id = {ha(s["entity_id"]): s for s in AMBER}
    monkeypatch.setattr(dynamic_price, "_states", lambda store, ids: {i: by_id[i] for i in ids if i in by_id})
    s = settings(**dynamic_price.related(ha("sensor.roseville_general_price"), AMBER))
    snap = scheduler.ha_price_snapshot(s, None)
    scheduler.price_events(snap, s)
    assert snap["tariff.price_spike"] == 0 and snap["tariff.demand_window_active"] == 1
