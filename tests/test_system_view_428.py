"""#428 phase 1: the System view overlay — its payload, its route, and its hook into the UI.

The payload comes from the poller's cache only; opening the view must never reach an aGate.
"""
import pathlib

import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import app as app_module
from franklinwh_direct_connect_bridge import client as client_module
from franklinwh_direct_connect_bridge import state, system_view

TPL = pathlib.Path(__file__).resolve().parents[1] / "src/franklinwh_direct_connect_bridge/templates"


def us_summary(**power):
    """A typical US site: split-phase, one aGate, one aPower, no solar, Emergency Backup."""
    p = {"soc": 100.0, "grid_w": 820.0, "solar_w": 0.0, "battery_w": 0.0, "load_w": 820.0,
         "generator_w": 0.0, "kwh_gen": 0, "mode": "Emergency Backup", "run_status": 0,
         "run_status_desc": "Standby", "off_grid": False, "grid_present": True,
         "grid_voltage_v": 241.6, "grid_freq_hz": 60.0, "grid_leg_v": [120.8, 120.8]}
    p.update(power)
    return {"ok": True, "power": p, "battery": {"soc": p["soc"], "count": None},
            "energy_today": {"solar": 0.0}, "circuits_on": {"1": True, "2": True, "3": False},
            "mode": {"modes": [{"name": "Emergency Backup", "reserved_soc": 100, "active": True},
                               {"name": "Time-of-Use", "reserved_soc": 20, "active": False}]},
            "firmware": {"FHP_SN": ["SYNTHETIC-A1"]}}


@pytest.fixture(autouse=True)
def _clean():
    state.reset_gateways()
    yield
    state.reset_gateways()


def gw(id_="gw1", summary=None, label="aGate"):
    g = state.register_gateway(id_, "127.0.0.1:9000", label)
    g.last_summary = summary
    return g


def test_the_typical_us_site_maps_without_guessing():
    g = system_view.gateway_payload(gw(summary=us_summary()))
    assert g["online"] and g["mode"] == "Emergency Backup" and g["inverter"] == "Standby"
    assert g["reserve_pct"] == 100
    assert g["grid"] == {"state": "connected", "power_w": 820.0, "voltage_v": 241.6, "freq_hz": 60.0}
    assert g["battery"] == {"soc_pct": 100.0, "power_w": 0.0, "count": 1}
    assert g["solar"] == [] and g["generator"] is None
    assert [(c["id"], c["on"]) for c in g["circuits"]] == [(1, True), (2, True), (3, False)]


def test_solar_shows_when_producing_or_produced_today():
    assert system_view.gateway_payload(gw("a", us_summary(solar_w=1200.0)))["solar"][0]["power_w"] == 1200.0
    s = us_summary()
    s["energy_today"]["solar"] = 3.1        # night now, but it produced today
    assert system_view.gateway_payload(gw("b", s))["solar"] != []


def test_an_off_grid_aGate_is_an_outage():
    assert system_view.gateway_payload(gw(summary=us_summary(off_grid=True)))["grid"]["state"] == "outage"


def test_a_cold_or_failed_cache_is_offline_not_zeros():
    g = system_view.gateway_payload(gw(summary=None))
    assert g["online"] is False and g["grid"]["power_w"] is None and g["battery"]["soc_pct"] is None


def test_the_route_reads_only_the_cache(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("the System view must not talk to an aGate")
    for name in ("summary", "power", "firmware", "device_model"):
        monkeypatch.setattr(client_module, name, boom, raising=False)
    gw("gw1", us_summary())
    gw("gw2", None, label="Garage")
    state.set_default("gw2")
    r = TestClient(app_module.create_app()).get("/api/system")
    assert r.status_code == 200
    body = r.json()
    assert [g["id"] for g in body["gateways"]] == ["gw2", "gw1"]      # the active one first
    sc = body["gateways"][1]["scenes"]["landscape"]
    assert {n["id"] for n in sc["nodes"]} == {"agate", "grid", "home", "battery", "sc1", "sc2", "sc3"}
    assert "portrait" in body["gateways"][0]["scenes"]


def test_the_overlay_files_are_served():
    c = TestClient(app_module.create_app())
    assert c.get("/system-view/system-view.js").status_code == 200
    assert c.get("/system-view/system-view.css").status_code == 200


def test_the_ui_hooks_are_one_mount_a_sidebar_entry_and_a_topbar_button():
    index = (TPL / "index.html").read_text()
    assert 'FWHSystemView.mount({endpoint: "api/system", below: "header", above: "nav.fixed.bottom-0"})' in index
    assert "system-view/system-view.css" in index and "system-view/system-view.js" in index
    for part in ("partials/sidebar.html", "partials/topbar.html"):
        assert "FWHSystemView.open()" in (TPL / part).read_text(), part
