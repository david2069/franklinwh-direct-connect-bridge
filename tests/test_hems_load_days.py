"""Heavy loads in the load forecast (owner 2026-11-25): each load's run times can be limited
to days of the week (hems 0.3.2), and the loads declared in HEMS setup are taken out of the
learnt base and added back on their own days and hours, so a Tuesday-night EV charge is
forecast on Tuesday nights, not spread over every weekday."""
import datetime as dt
import pathlib

from franklinwh_direct_connect_bridge import hems_setup, load_forecast, smart_dispatch

from test_smart_dispatch_p1 import NOW, TZ, st, tariff  # noqa: F401  (fixture)

PKG = pathlib.Path(__file__).resolve().parents[1] / "src" / "franklinwh_direct_connect_bridge"
EV = {"name": "EV", "device_type": "ev_charger", "measurement": {"kind": "nameplate"},
      "power_kw": 7.0, "runs": [{"start": "22:00", "end": "23:00", "days": [1]}],
      "circuit": "general"}


def _seed(s, days=35):
    """1 kW base, plus 7 kW on Tuesdays 22:00–23:00."""
    start = int(NOW) // 3600 * 3600 - days * 86400
    for t in range(start, int(NOW), 900):
        local = dt.datetime.fromtimestamp(t, TZ)
        w = 1000 + (7000 if local.weekday() == 1 and local.hour == 22 else 0)
        s.insert({"load_w": w}, t, gateway_id="gw1")


def _at(pts, weekday, hour):
    for p in pts:
        local = dt.datetime.fromtimestamp(p["start"], TZ)
        if local.weekday() == weekday and local.hour == hour:
            return p["kwh"]
    raise AssertionError("hour not in the forecast")


def test_a_declared_load_is_forecast_on_its_own_days(st):  # noqa: F811
    _seed(st)
    hems_setup.save(st, "gw1", {"opted_in": True, "loads": [EV]})
    pts = load_forecast.predict(st, "gw1", {}, None, NOW)        # Tue 00:20 → 48 h ahead
    assert abs(_at(pts, 1, 22) - 8.0) < 0.3                      # Tuesday 22:00
    assert abs(_at(pts, 2, 22) - 1.0) < 0.3                      # Wednesday 22:00


def test_without_the_load_declared_it_is_spread_over_the_weekdays(st):  # noqa: F811
    _seed(st)
    pts = load_forecast.predict(st, "gw1", {}, None, NOW)
    assert _at(pts, 1, 22) < 7.0 and _at(pts, 2, 22) > 1.5


def test_loads_are_used_only_while_hems_setup_is_on(st):  # noqa: F811
    _seed(st)
    hems_setup.save(st, "gw1", {"opted_in": False, "loads": [EV]})
    pts = load_forecast.predict(st, "gw1", {}, None, NOW)
    assert _at(pts, 1, 22) < 7.0


def test_plan_inputs_count_the_heavy_loads(st):  # noqa: F811
    _seed(st, days=3)
    hems_setup.save(st, "gw1", {"opted_in": True, "loads": [EV]})
    tariff(st)
    v = smart_dispatch.view(st, None, "gw1", NOW)
    home = {i["key"]: i for i in v["inputs"]}["home_load"]
    assert "1 heavy load from HEMS setup" in home["value"]


def test_both_forms_have_a_days_picker():
    wiz = (PKG / "templates/partials/setup_wizard.html").read_text()
    card = (PKG / "templates/tabs/settings.html").read_text()
    assert 'data-testid="hems-wiz-days"' in wiz and 'data-testid="hems-days"' in card
    for js in ("static/js/setup_wizard.js", "static/js/settings_tab.js"):
        assert "_days: this.loadDays(ld)" in (PKG / js).read_text(), js
