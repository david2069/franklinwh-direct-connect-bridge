"""Smart Dispatch plan inputs (owner 2026-11-25): a new install planned the home at 0 kWh, the
load forecast having too little history. The home load now falls back to the hour-of-day
average (one day of history is enough), then the always-on load from HEMS setup, and says
which it used. A Plan inputs card says what the plan is using, with Re-run HEMS setup."""
import pathlib

from franklinwh_direct_connect_bridge import hems_setup, smart_dispatch

from test_smart_dispatch_p1 import NOW, seed_load, st, tariff  # noqa: F401  (fixture)

PKG = pathlib.Path(__file__).resolve().parents[1] / "src" / "franklinwh_direct_connect_bridge"


def _plan(s):
    tariff(s)
    smart_dispatch.save(s, "gw1", {"objective": "lowest_cost", "grid_charge": "allowed"})
    return smart_dispatch.view(s, None, "gw1", NOW)


def test_one_day_of_history_plans_every_step(st):  # noqa: F811
    seed_load(st, days=1)
    r = _plan(st)["result"]
    assert all(s["load_kw"] > 0 for s in r["steps"])
    assert not any(a.startswith("No load forecast") for a in r["assumptions"])
    assert any("hour-of-day" in a for a in r["assumptions"])


def test_without_history_the_always_on_load_is_used_and_said(st):  # noqa: F811
    hems_setup.save(st, "gw1", {"always_on_kw": 0.6})
    r = _plan(st)["result"]
    assert {s["load_kw"] for s in r["steps"]} == {0.6}
    assert any("always-on load" in a for a in r["assumptions"])


def test_without_history_or_always_on_it_still_says_zero(st):  # noqa: F811
    r = _plan(st)["result"]
    assert any(a.startswith("No load forecast for 48 of 48") for a in r["assumptions"])


def test_plan_inputs_say_what_the_plan_uses(st):  # noqa: F811
    seed_load(st, days=3)
    v = _plan(st)
    inputs = {i["key"]: i for i in v["inputs"]}
    assert list(inputs) == ["home_load", "solar", "battery", "tariff"]
    home = inputs["home_load"]
    assert "4 days of local history" in home["value"] and home["status"] == "partial"
    assert home["action"] == {"label": "Re-run HEMS setup", "wizard": "hems", "step": "usage"}
    assert inputs["solar"]["status"] == "missing"
    assert inputs["battery"]["status"] == "ok" and "13.6 kWh" in inputs["battery"]["value"]
    assert inputs["tariff"]["status"] == "ok"


def test_plan_inputs_show_before_a_plan_can_be_made(st):  # noqa: F811
    v = smart_dispatch.view(st, None, "gw1", NOW)
    inputs = {i["key"]: i for i in v["inputs"]}
    assert inputs["tariff"]["status"] == "missing"
    assert inputs["home_load"]["status"] == "missing"
    assert "No local history yet" in inputs["home_load"]["value"]


def test_hems_setup_says_how_much_history_there_is(st):  # noqa: F811
    seed_load(st, days=3)
    assert hems_setup.view(st, None, "gw1", NOW)["history_days"] == 4


def test_the_tab_and_wizard_carry_plan_inputs_and_rerun():
    html = (PKG / "templates/tabs/smart_dispatch.html").read_text()
    assert 'data-testid="sd-inputs"' in html and 'data-testid="sd-rerun-hems"' in html
    assert html.index('data-testid="sd-inputs"') < html.index('data-testid="sd-decision"')
    wiz_js = (PKG / "static/js/setup_wizard.js").read_text()
    assert "t.step" in wiz_js                    # opens the HEMS steps at the asked step
    wiz = (PKG / "templates/partials/setup_wizard.html").read_text()
    assert 'data-testid="hems-wiz-history"' in wiz


def test_history_is_found_under_the_gateway_serial(st):  # noqa: F811
    """A real aGate's metrics rows carry its serial (poller: gw.serial or gw.id), not the
    gateway id: the load forecast, HEMS setup and Actuals found no history on real installs."""
    from franklinwh_direct_connect_bridge import state
    state.get_gateway("gw1").serial = "SER-TEST-1"
    start = int(NOW) // 3600 * 3600 - 3 * 86400
    for t in range(start, int(NOW), 900):
        st.insert({"load_w": 1000, "soc": 50, "battery_w": 0}, t, gateway_id="SER-TEST-1")
    assert hems_setup.view(st, None, "gw1", NOW)["history_days"] == 4
    r = _plan(st)["result"]
    assert all(s["load_kw"] > 0 for s in r["steps"])
    assert smart_dispatch.actuals(st, "gw1", NOW)["steps"]
