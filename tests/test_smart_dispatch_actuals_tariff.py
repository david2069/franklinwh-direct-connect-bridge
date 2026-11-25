"""Smart Dispatch (owner 2026-11-25): Actuals from the start of the day to now beside the plan,
and the tariff shown on the plan: time-of-use bands, demand-charge windows, an export bonus
and an export penalty, shaded on the chart (each a filter) and as bands under it."""
import datetime as dt
import pathlib

from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import app as app_module, db, smart_dispatch

from test_smart_dispatch_p1 import NOW, TZ, seed_load, st, tariff  # noqa: F401  (fixture)

PKG = pathlib.Path(__file__).resolve().parents[1] / "src" / "franklinwh_direct_connect_bridge"
MIDNIGHT = int(dt.datetime(2026, 11, 17, 0, 0, tzinfo=TZ).timestamp())


def test_each_step_carries_its_band_and_demand_rate(st):  # noqa: F811
    tariff(st)
    seed_load(st)
    smart_dispatch.save(st, "gw1", {"objective": "lowest_cost", "grid_charge": "allowed"})
    steps = smart_dispatch.view(st, None, "gw1", NOW)["result"]["steps"]
    by_hour = {dt.datetime.fromtimestamp(s["start"], TZ).hour: s for s in steps}
    assert by_hour[16]["band"] == "on_peak" and by_hour[10]["band"] == "off_peak"
    assert all(s["demand_rate"] == 0.0 for s in steps)


def test_actuals_from_the_site_midnight_to_now(st):  # noqa: F811
    # battery_w > 0 discharges; the plan's battery_kw > 0 charges: the actuals use the plan's sign.
    for t in range(MIDNIGHT - 3600, int(NOW) + 1, 60):
        st.insert({"battery_w": -2000, "soc": 40, "grid_w": 2500, "solar_w": 0, "load_w": 500},
                  t, gateway_id="gw1")
    a = smart_dispatch.actuals(st, "gw1", NOW)
    assert a["start"] == MIDNIGHT and a["end"] == int(NOW)
    assert [r["start"] for r in a["steps"]] == [MIDNIGHT]          # 00:00–00:30 so far
    r = a["steps"][0]
    assert (r["battery_kw"], r["soc_pct"], r["import_kw"], r["export_kw"]) == (2.0, 40.0, 2.5, 0.0)


def test_no_samples_no_actuals(st):  # noqa: F811
    assert smart_dispatch.actuals(st, "gw1", NOW)["steps"] == []


def test_the_actuals_api(st, monkeypatch):  # noqa: F811
    monkeypatch.setattr(db, "get_store", lambda s: st)
    st.insert({"battery_w": 1000, "soc": 50}, int(NOW) - 60, gateway_id="gw1")
    c = TestClient(app_module.create_app())
    d = c.get("/api/smart-dispatch/actuals?gateway=gw1").json()
    assert "steps" in d and "start" in d


def test_the_tab_has_actuals_tariff_filters_and_bands():
    html = (PKG / "templates/tabs/smart_dispatch.html").read_text()
    js = (PKG / "static/js/smart_dispatch_tab.js").read_text()
    for tid in ("sd-actuals", "sd-actual-kw", "sd-actual-soc", "sd-tariff-tou",
                "sd-tariff-demand", "sd-tariff-bonus", "sd-tariff-penalty",
                "sd-view-chart", "sd-view-tariff", "sd-bands"):
        assert f'data-testid="{tid}"' in html, tid
    assert "api/smart-dispatch/actuals" in js
    assert "tariffShade" in js                     # the chart plugin that shades the windows


def test_the_plan_sums_sources_loads_and_exports(st):  # noqa: F811
    """Owner 2026-11-25: a summary at the top of the plan's energy: sources, loads, exports."""
    tariff(st)
    seed_load(st)
    smart_dispatch.save(st, "gw1", {"objective": "lowest_cost", "grid_charge": "allowed"})
    r = smart_dispatch.view(st, None, "gw1", NOW)["result"]
    steps, e = r["steps"], r["energy"]
    h = 0.5
    load = round(sum(s["load_kw"] * h for s in steps), 2)
    imp = round(sum(s["grid_import_kwh"] for s in steps), 2)
    chg = round(sum(max(s["battery_kw"], 0) * h for s in steps), 2)
    dis = round(sum(max(-s["battery_kw"], 0) * h for s in steps), 2)
    assert e["load_kwh"] == load and e["import_kwh"] == imp
    assert e["battery_charge_kwh"] == chg and e["battery_discharge_kwh"] == dis
    assert set(e) >= {"solar_kwh", "export_kwh", "battery_export_kwh", "curtailed_kwh"}
    assert load > 0


def test_the_table_is_folded_and_the_summary_is_at_the_top():
    html = (PKG / "templates/tabs/smart_dispatch.html").read_text()
    assert 'data-testid="sd-energy"' in html and 'data-testid="sd-steps-toggle"' in html
    assert html.index('data-testid="sd-energy"') < html.index('data-testid="sd-chart"')
    js = (PKG / "static/js/smart_dispatch_tab.js").read_text()
    assert "stepsOpen: false" in js


def test_create_always_answers_831():
    """#831: with nothing to create the button was disabled, so a click said nothing."""
    html = (PKG / "templates/tabs/smart_dispatch.html").read_text()
    i = html.index('data-testid="sd-create"')
    btn = html[i:html.index("</button>", i)]
    assert "drafts.tasks.length" not in btn             # not disabled for an empty plan
    js = (PKG / "static/js/smart_dispatch_tab.js").read_text()
    c = js[js.index("async createSchedules()"):js.index("async setAuto(")]
    assert "Nothing to create" in c
