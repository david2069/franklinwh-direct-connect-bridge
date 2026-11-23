"""#713 step 5 (owner 2026-11-17): an opt-in HEMS setup screen on hems.loads. Off until the
user opts in, with hems's notice. The always-on load and the usage periods are pre-filled from
the gateway's own history (please confirm); each heavy load is checked by hems against what
this bridge can control (its capabilities)."""
import datetime as dt
import pathlib

import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import app as app_module
from franklinwh_direct_connect_bridge import battery_control, db, hems_setup, setup_wizard, state
from franklinwh_direct_connect_bridge.db import MetricsStore

PKG = pathlib.Path(__file__).resolve().parents[1] / "src" / "franklinwh_direct_connect_bridge"
NOW = dt.datetime(2026, 11, 17, 10, 20, tzinfo=dt.timezone(dt.timedelta(hours=11))).timestamp()

POOL = {"name": "Pool pump", "device_type": "pool_pump",
        "measurement": {"kind": "nameplate"}, "power_kw": 1.1, "duration_h": 6,
        "runs": [{"start": "10:00", "end": "16:00"}], "circuit": "smart_circuit",
        "control": {"type": "deferrable", "energy_kwh": 6.6, "deadline": "18:00"},
        "switch": {"kind": "smart_circuit", "circuit": 1}}


@pytest.fixture
def st(tmp_path):
    s = MetricsStore(str(tmp_path / "m.db"))
    setup_wizard.set_site_timezone(s, "Australia/Sydney")
    state.reset_gateways()
    yield s
    state.reset_gateways()
    s.close()


def seed(st, days, gw="gw1"):
    start = int(NOW) // 3600 * 3600 - days * 86400
    for t in range(start, int(NOW), 900):
        h = dt.datetime.fromtimestamp(t, dt.timezone(dt.timedelta(hours=11))).hour
        st.insert({"load_w": 1500 if 17 <= h < 21 else 300 if h < 6 else 700}, t, gateway_id=gw)


def test_off_until_opted_in_with_hems_notice(st):
    r = hems_setup.view(st, None, "gw1", NOW)
    assert r["opted_in"] is False and r["notice"] == "Planning is only as accurate as your answers."


def test_always_on_and_usage_periods_prefilled_to_confirm(st):
    seed(st, 14)
    r = hems_setup.view(st, None, "gw1", NOW)
    assert r["always_on"]["value_kw"] == pytest.approx(0.3, abs=0.02) and r["always_on"]["confirm"]
    assert r["periods"]["weekday"][18] == "high" and r["periods"]["weekday"][3] == "low"
    assert r["periods"]["confirm"] is True
    hems_setup.save(st, "gw1", {"opted_in": True, "always_on_kw": 0.35, "periods_confirmed": True})
    r = hems_setup.view(st, None, "gw1", NOW)
    assert r["opted_in"] and r["always_on"] == {"value_kw": 0.35, "confirm": False, "basis": "yours"}
    assert r["periods"]["confirm"] is False


def test_each_load_is_checked_against_the_bridges_capabilities(st, monkeypatch):
    gw = state.register_gateway("gw1", "192.0.2.10", "gw1")
    monkeypatch.setattr(battery_control, "is_enabled", lambda *a, **k: False)
    monkeypatch.setattr(hems_setup, "_circuits", lambda *a: 0)          # none installed
    hems_setup.save(st, "gw1", {"opted_in": True, "loads": [POOL, {"name": "Heater"}]})
    r = hems_setup.view(st, None, "gw1", NOW)
    assert "smart_circuits" not in r["capabilities"] and "mode" in r["capabilities"]
    pool, heater = r["loads"]
    assert pool["problems"] == ["switching by smart circuit needs the smart_circuits capability"]
    assert "device type: missing" in heater["problems"]
    monkeypatch.setattr(hems_setup, "_circuits", lambda *a: 2)
    monkeypatch.setattr(battery_control, "is_enabled", lambda *a, **k: True)
    r = hems_setup.view(st, None, "gw1", NOW)
    assert {"smart_circuits", "battery_power_w", "target_soc"} <= set(r["capabilities"])
    assert r["loads"][0]["problems"] == []


def test_a_scheduled_load_shows_its_expected_hours(st, monkeypatch):
    monkeypatch.setattr(hems_setup, "_circuits", lambda *a: 2)
    hems_setup.save(st, "gw1", {"opted_in": True, "loads": [POOL]})
    r = hems_setup.view(st, None, "gw1", NOW)
    assert r["loads"][0]["expected_kwh_today"] == pytest.approx(6.6)


def test_unknown_fields_are_refused(st):
    with pytest.raises(ValueError):
        hems_setup.save(st, "gw1", {"nope": 1})


def test_the_api_and_the_screen(tmp_path, monkeypatch):
    s = MetricsStore(str(tmp_path / "m.db"))
    monkeypatch.setattr(db, "get_store", lambda *a, **k: s)
    state.reset_gateways()
    state.register_gateway("gw1", "192.0.2.10", "gw1")
    c = TestClient(app_module.create_app())
    assert c.get("/api/hems/setup", params={"gateway": "gw1"}).json()["opted_in"] is False
    r = c.put("/api/hems/setup", params={"gateway": "gw1"}, json={"opted_in": True})
    assert r.status_code == 200 and r.json()["opted_in"] is True
    assert c.put("/api/hems/setup", params={"gateway": "gw1"}, json={"x": 1}).status_code == 422
    html = (PKG / "templates" / "tabs" / "settings.html").read_text()
    assert 'data-testid="hems-setup"' in html and 'data-testid="hems-optin"' in html
    assert "hems-add-load" in html and "Please confirm" in html
    state.reset_gateways()


def test_device_type_is_a_list_with_labels(st):
    """Owner 2026-11-24: Device type is a drop-down of hems's types (value + label), not free
    text; a typed value that isn't one is flagged, and kept so nothing is lost."""
    choices = hems_setup.view(st, None, "gw1", NOW)["choices"]["device_type"]
    assert {"value": "ev_charger", "label": "EV charger"} in choices
    assert choices[-1]["value"] == "other"
    hems_setup.save(st, "gw1", {"opted_in": True, "loads": [{**POOL, "device_type": "EV charger"}]})
    ld = hems_setup.view(st, None, "gw1", NOW)["loads"][0]
    assert ld["device_type"] == "EV charger"
    assert any(p.startswith("device type: one of") for p in ld["problems"])
    for f in ("templates/tabs/settings.html", "templates/partials/setup_wizard.html"):
        html = (PKG / f).read_text()
        assert 'placeholder="pool_pump' not in html
        assert "choices.device_type" in html and 'data-testid="hems-device-type"' in html
