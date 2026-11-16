"""#675: each site has its own location and PV array (owner 2026-11-16: "location is always
the default gateway's location. Assumption is all gateways are co-located, we should
check. Split location"; design approved: location + PV array per site, a Site picker on
Location & Solar, and each gateway on the site with its own reported location).

The default site keeps the values Location & Solar always had (Settings ``pv_*``); every
other site has its own. A gateway uses its site's (gateway → meter → site; no meter → the
default site)."""
import pathlib

import pytest

from franklinwh_direct_connect_bridge import config, site_location
from franklinwh_direct_connect_bridge.db import MetricsStore

PKG = pathlib.Path(__file__).resolve().parents[1] / "src" / "franklinwh_direct_connect_bridge"


@pytest.fixture
def s(monkeypatch):
    s = config.get_settings()
    for k, v in (("pv_latitude", -33.7843), ("pv_longitude", 151.1883), ("pv_kwp", 6.6),
                 ("pv_tilt", 20.0), ("pv_azimuth", 0.0)):
        monkeypatch.setattr(s, k, v)
    monkeypatch.setattr(config, "save_override", lambda k, v: None)
    return s


@pytest.fixture
def st(tmp_path):
    st = MetricsStore(str(tmp_path / "m.db"))
    st.create_site(sid="home", name="Home", is_default=True)
    st.create_site(sid="farm", name="Farm")
    st.create_meter(mid="m1", site_id="home", name="Main", is_default=True)
    st.create_meter(mid="m2", site_id="farm", name="Shed")
    yield st
    st.close()


def test_the_default_site_keeps_location_and_solar_and_others_have_their_own(s, st):
    home = site_location.values(s, st, st.site("home"))
    assert home == {"latitude": -33.7843, "longitude": 151.1883, "pv_kwp": 6.6,
                    "pv_tilt": 20.0, "pv_azimuth": 0.0}
    farm = site_location.values(s, st, st.site("farm"))
    assert farm == {"latitude": None, "longitude": None, "pv_kwp": None, "pv_tilt": None,
                    "pv_azimuth": None}
    site_location.save(s, st, st.site("farm"), {"latitude": -27.47, "longitude": 153.021,
                                                "pv_kwp": 10.0, "pv_tilt": 15, "pv_azimuth": -10})
    assert site_location.values(s, st, st.site("farm"))["latitude"] == -27.47
    assert s.pv_latitude == -33.7843                     # the default site's are untouched
    site_location.save(s, st, st.site("farm"), {"pv_kwp": None})          # Use gateway
    assert site_location.values(s, st, st.site("farm"))["pv_kwp"] is None


def test_saving_the_default_site_writes_location_and_solar(s, st, monkeypatch):
    saved = {}
    monkeypatch.setattr(config, "save_override", lambda k, v: saved.__setitem__(k, v))
    site_location.save(s, st, st.site("home"), {"latitude": -33.9, "pv_kwp": None})
    assert saved == {"pv_latitude": -33.9, "pv_kwp": None}
    assert s.pv_latitude == -33.9 and s.pv_kwp is None
    assert st.site("home")["latitude"] is None            # not a second copy


def test_a_gateway_uses_its_sites_location(s, st, monkeypatch):
    monkeypatch.setattr(st, "gateways", lambda: [
        {"id": "g1", "meter_id": "m1"}, {"id": "g2", "meter_id": "m2"}, {"id": "g3", "meter_id": None}])
    site_location.save(s, st, st.site("farm"), {"latitude": -27.47, "longitude": 153.021})
    assert site_location.site_of_gateway(st, "g2")["id"] == "farm"
    assert site_location.site_of_gateway(st, "g3")["id"] == "home"     # no meter: the default
    assert site_location.site_of_gateway(st, "gX")["id"] == "home"
    assert site_location.gateway_ids(st, st.site("home")) == ["g1", "g3"]
    assert site_location.gateway_ids(st, st.site("farm")) == ["g2"]
    assert site_location.for_gateway(s, st, "g2", derived=lambda ids: None)["latitude"] == -27.47
    assert site_location.for_gateway(s, st, "g1", derived=lambda ids: None)["latitude"] == -33.7843


def test_pv_size_is_the_sites_own_else_its_gateways(s, st, monkeypatch):
    monkeypatch.setattr(st, "gateways", lambda: [
        {"id": "g1", "meter_id": "m1"}, {"id": "g2", "meter_id": "m2"}])
    asked = []

    def derived(ids):
        asked.append(ids)
        return {("g2",): 8.2, ("g1",): 6.0}[tuple(ids)]
    farm = site_location.effective(s, st, st.site("farm"), derived=derived)
    assert farm["kwp"] == 8.2 and farm["kwp_source"] == "gateway" and asked == [["g2"]]
    home = site_location.effective(s, st, st.site("home"), derived=derived)
    assert home["kwp"] == 6.6 and home["kwp_source"] == "you" and home["derived"] == 6.0


def test_no_sites_at_all_is_the_default_site(s, tmp_path):
    st = MetricsStore(str(tmp_path / "empty.db"))
    assert site_location.site_of_gateway(st, "g1") is None
    assert site_location.values(s, st, None)["latitude"] == -33.7843
    st.close()


# ── are the gateways at the same place? ──────────────────────────────────────
def test_distance():
    assert site_location.distance_km(-33.7843, 151.1883, -33.7843, 151.1883) == 0
    assert 720 < site_location.distance_km(-33.7843, 151.1883, -27.47, 153.021) < 728   # Sydney–Brisbane


def test_each_gateway_is_checked_against_its_site():
    loc = {"latitude": -33.7843, "longitude": 151.1883}
    rows = site_location.check(loc, {
        "g1": {"latitude": -33.7850, "longitude": 151.1890},
        "g2": {"latitude": -27.47, "longitude": 153.021},
        "g3": None})                                       # didn't report one
    by = {r["gateway_id"]: r for r in rows}
    assert by["g1"]["same_place"] is True and by["g1"]["distance_km"] < 1
    assert by["g2"]["same_place"] is False and round(by["g2"]["distance_km"]) == 724
    assert by["g3"]["same_place"] is None and by["g3"]["latitude"] is None
    assert site_location.check({"latitude": None, "longitude": None},
                               {"g1": {"latitude": 1, "longitude": 2}})[0]["same_place"] is None


# ── the page ─────────────────────────────────────────────────────────────────
def test_location_and_solar_has_a_site_picker_and_the_gateways_check():
    html = (PKG / "templates" / "tabs" / "settings.html").read_text()
    i = html.index("<!-- ══ Location & Solar ══ -->")
    card = html[i:html.index("<!-- ══ Prices (#582)")]
    for tid in ("location-site", "location-gateways"):
        assert f'data-testid="{tid}"' in card, tid
    assert "saveLoc(" in card and "saveOne({pv_" not in card     # the picked site's, not always the default's
    js = (PKG / "static" / "js" / "settings_tab.js").read_text()
    assert "api/sites/' + " in js and "/location" in js


# ── the API ──────────────────────────────────────────────────────────────────
@pytest.fixture
def api(s, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from franklinwh_direct_connect_bridge import app as app_module, client as client_module, \
        db, mockgw, state, supervisor
    state.reset_gateways()
    st = MetricsStore(str(tmp_path / "api.db"))
    monkeypatch.setattr(db, "get_store", lambda *a, **k: st)

    async def _noop(*a, **k):
        return None
    monkeypatch.setattr(supervisor, "start_poller", _noop)
    monkeypatch.setattr(supervisor, "stop_poller", _noop)
    monkeypatch.setattr(supervisor, "is_running", lambda gid: True)
    monkeypatch.setattr(mockgw, "stop_mock", lambda gid: None)
    monkeypatch.setattr(client_module, "writes_enabled", lambda s: True)
    from franklinwh_direct_connect_bridge import pv_size     # no gateway to ask for its size
    monkeypatch.setattr(pv_size, "derived_kwp", lambda read=False, gateway_ids=None: None)
    reported = {"192.0.2.1": {"laitude": "-33.7850", "longitude": "151.1890"},   # FranklinWH's spelling
                "192.0.2.2": {"laitude": "-27.4700", "longitude": "153.0210"}}
    monkeypatch.setattr(client_module, "read",
                        lambda settings, cmd, host=None: reported[host] if cmd == "time_location" else {})
    st.create_site(sid="home", name="Home", is_default=True)
    st.create_site(sid="farm", name="Farm")
    st.create_meter(mid="m1", site_id="home", name="Main", is_default=True)
    st.create_meter(mid="m2", site_id="farm", name="Shed")
    for gid, host, meter in (("g1", "192.0.2.1", "m1"), ("g2", "192.0.2.2", "m1")):
        st.create_gateway(gw_id=gid, label=gid.upper(), host=host)
        st.update_gateway(gid, meter_id=meter)
        state.register_gateway(gid, host, gid.upper())
    c = TestClient(app_module.create_app())
    yield c, st
    state.reset_gateways()
    st.close()


def test_api_shows_the_site_and_flags_a_gateway_somewhere_else(api):
    c, _st = api
    v = c.get("/api/sites/home/location").json()
    assert v["is_default"] and v["latitude"] == -33.7843 and v["pv_kwp"] == 6.6
    by = {g["gateway_id"]: g for g in v["gateways"]}
    assert by["g1"]["same_place"] is True and by["g1"]["name"] == "G1"
    assert by["g2"]["same_place"] is False and round(by["g2"]["distance_km"]) == 724


def test_api_saves_another_sites_own_and_sync_fills_the_gateways_site(api, s):
    c, st = api
    st.update_gateway("g2", meter_id="m2")                       # g2 moved to the Farm
    r = c.put("/api/sites/farm/location", json={"pv_kwp": 9.5, "pv_tilt": 15})
    assert r.status_code == 200 and r.json()["pv_kwp"] == 9.5
    assert c.post("/api/solar/sync-location?gateway=g2").json()["site_id"] == "farm"
    farm = st.site("farm")
    assert (farm["latitude"], farm["longitude"], farm["pv_kwp"]) == (-27.47, 153.021, 9.5)
    assert s.pv_latitude == -33.7843                             # the default site's unchanged
    v = c.get("/api/sites/farm/location").json()
    assert [g["gateway_id"] for g in v["gateways"]] == ["g2"] and v["gateways"][0]["same_place"]
    assert c.put("/api/sites/farm/location", json={"latitude": 91}).status_code == 422


def test_api_forecast_and_scheduler_use_the_gateways_site(api, s, monkeypatch):
    from franklinwh_direct_connect_bridge import scheduler, solar_forecast
    c, st = api
    st.update_gateway("g2", meter_id="m2")
    st.set_site_location("farm", latitude=-27.47, longitude=153.021, pv_kwp=9.5)
    asked = []
    monkeypatch.setattr(solar_forecast, "forecast",
                        lambda lat, lon, **k: asked.append((lat, lon, k["kwp"])) or {})
    monkeypatch.setattr(solar_forecast, "sensors", lambda fc: {"solar_forecast.x": 1})
    assert c.get("/api/solar/forecast?gateway=g2").json()["pv"]["site_id"] == "farm"
    assert c.get("/api/solar/forecast?gateway=g1").json()["pv"]["lat"] == -33.7843
    assert c.get("/api/solar/forecast").json()["pv"]["lat"] == -33.7843     # no gateway: the default
    assert scheduler.solar_snapshot(s, st, "g2") == {"solar_forecast.x": 1}
    assert asked[0] == (-27.47, 153.021, 9.5) and asked[-1] == (-27.47, 153.021, 9.5)
    assert scheduler.feature_states(s, st, "g2")["solar_forecast"]["state"] == "active"
    st.set_site_location("farm", latitude=None, longitude=None)
    assert scheduler.feature_states(s, st, "g2")["solar_forecast"]["state"] == "not_set_up"
