"""Prices in one place under Sites & Billing (#582): the AEMO region comes from the site
(AU-NSW → NSW1, no second picker), the price signal and price events sit under Billing,
a price spike and an HA demand window feed the scheduler, and the wholesale export
template uses the spike instead of a fixed 50 c."""
import logging
import pathlib
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import aemo_nem, app as app_module, scheduler
from franklinwh_direct_connect_bridge import client as client_module
from franklinwh_direct_connect_bridge.db import MetricsStore

PKG = pathlib.Path(__file__).resolve().parents[1] / "src" / "franklinwh_direct_connect_bridge"
HTML = (PKG / "templates" / "tabs" / "settings.html").read_text()


@pytest.mark.parametrize("site,nem", [("AU-NSW", "NSW1"), ("au-act", "NSW1"), ("VIC", "VIC1"),
                                      ("QLD1", "QLD1"), ("AU-SA", "SA1"), ("Tasmania", "TAS1"),
                                      ("AU-WA", None), ("US-CA", None), ("", None)])
def test_a_site_region_maps_to_its_nem_region(site, nem):
    assert aemo_nem.region_for(site) == nem


@pytest.fixture
def st(tmp_path):
    s = MetricsStore(str(tmp_path / "t.db"))
    s.create_site(sid="home", name="Home", region="AU-VIC", is_default=True)
    s.create_meter(mid="m1", site_id="home", is_default=True)
    return s


def test_the_price_signal_reads_the_sites_region(st, monkeypatch):
    asked = []
    monkeypatch.setattr(aemo_nem, "spot_price", lambda r: asked.append(r) or {"price_c_kwh": 9.0})
    out = scheduler.nem_snapshot(SimpleNamespace(nem_region="NSW1"), st, None)
    assert asked == ["VIC1"] and out == {"tariff.spot_price": 9.0}
    assert scheduler.nem_snapshot(SimpleNamespace(nem_region=""), st, None) == {}, "off stays off"


def test_a_dynamic_tariff_reads_the_sites_region(st, monkeypatch):
    asked = []
    monkeypatch.setattr(aemo_nem, "spot_price", lambda r: asked.append(r) or {"price_c_kwh": 12.0})
    monkeypatch.setattr(scheduler, "tariff_dynamic_provider",
                        lambda store, gw: {"source": "nem", "region": "NSW1"})
    snap = {}
    scheduler.apply_dynamic_pricing(snap, None, st, None)
    assert asked == ["VIC1"] and snap["tariff.spot_price"] == 12.0


def _s(**kw):
    base = dict(price_spike_c=0.0, price_spike_entity="", demand_window_entity="")
    return SimpleNamespace(**{**base, **kw})


def test_a_price_spike_from_the_threshold():
    snap = {"tariff.spot_price": 60.0}
    scheduler.price_events(snap, _s(price_spike_c=50))
    assert snap["tariff.price_spike"] == 1 and snap["tariff.spike_threshold"] == 50
    snap = {"tariff.spot_price": 40.0}
    scheduler.price_events(snap, _s(price_spike_c=50))
    assert snap["tariff.price_spike"] == 0
    snap = {"tariff.spot_price": 400.0}
    scheduler.price_events(snap, _s())
    assert snap.get("tariff.price_spike") is None, "no threshold and no sensor: no reading"


def test_an_ha_spike_sensor_wins():
    snap = {"tariff.spot_price": 10.0, "ha:home:binary_sensor.spike": 1}
    scheduler.price_events(snap, _s(price_spike_c=50, price_spike_entity="ha:home:binary_sensor.spike"))
    assert snap["tariff.price_spike"] == 1


def test_an_ha_demand_window_wins_over_the_tariffs():
    snap = {"tariff.demand_window_active": 0, "ha:home:calendar.peak": 1}
    scheduler.price_events(snap, _s(demand_window_entity="ha:home:calendar.peak"))
    assert snap["tariff.demand_window_active"] == 1
    snap = {"tariff.demand_window_active": 1}
    scheduler.price_events(snap, _s())
    assert snap["tariff.demand_window_active"] == 1, "no entity: the tariff's stands"


def test_the_spike_sensors_are_in_the_picker():
    ids = {s for s, _ in scheduler.TARIFF_SENSORS}
    assert {"tariff.price_spike", "tariff.spike_threshold"} <= ids


def test_the_wholesale_export_template_uses_the_spike():
    p = next(p for p in scheduler.PRESETS if p["id"] == "spot_high_export_ask")
    conds = p["spec"]["conditions"]
    assert {"sensor": "tariff.price_spike", "op": "==", "value": 1} in conds
    assert not any(c.get("sensor") == "tariff.spot_price" for c in conds)


def test_saved_region_moves_to_the_site(tmp_path, caplog):
    s = MetricsStore(str(tmp_path / "t.db"))
    s.create_site(sid="a", name="A", region="", is_default=True)
    s.create_site(sid="b", name="B", region="AU-NSW")
    with caplog.at_level(logging.WARNING):
        aemo_nem.migrate_region(s, SimpleNamespace(nem_region="VIC1"))
    assert s.site("a")["region"] == "AU-VIC"
    assert s.site("b")["region"] == "AU-NSW", "a site's own region is never overwritten"
    assert any("B" in r.getMessage() and "VIC1" in r.getMessage() for r in caplog.records)


@pytest.fixture
def c(monkeypatch):
    monkeypatch.setattr(client_module, "writes_enabled", lambda s: True)
    return TestClient(app_module.create_app())


def test_the_price_events_save(c):
    r = c.put("/api/settings", json={"price_spike_c": 45.5,
                                     "price_spike_entity": "ha:home:binary_sensor.spike",
                                     "demand_window_entity": "ha:home:calendar.peak"})
    assert r.status_code == 200, r.text
    d = c.get("/api/settings").json()["prices"]
    assert d["price_spike_c"] == 45.5 and d["demand_window_entity"] == "ha:home:calendar.peak"


def test_prices_sit_under_billing_and_leave_integrations():
    assert "Wholesale region (AEMO NEM)" not in HTML
    assert "Dynamic price (wholesale)" not in HTML
    for tid in ("prices-section", "price-signal-source", "price-spike-threshold",
                "price-spike-entity", "demand-window-entity"):
        assert f'data-testid="{tid}"' in HTML, tid
    i = HTML.index('data-testid="prices-section"')
    assert HTML.rfind("x-show=\"sub==='billing'\"", 0, i) > HTML.rfind("x-show=\"sub==='integrations'\"", 0, i)
