"""Smart Dispatch, plan only (owner 2026-11-24, #612 §7 phase 1, hems.dispatch).

A plan like FWHAI Smart Dispatch, driven by battery SoC, prices, solar and home load. Once a
utility plan is entered the user is asked their target (Emergency Backup only, TOU, lowest
cost with demand charges, self-consumption, most export earnings), the SoC band and the
utility's limits (grid charging and export: allowed, limited, prohibited). Phase 1 shows the
plan and the action now; it never writes to the gateway."""
import datetime as dt
import pathlib

import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import (app as app_module, battery_control, config, db,
                                              environment, load_forecast, setup_wizard,
                                              smart_dispatch, state, system_setup, tab_access)
from franklinwh_direct_connect_bridge.db import MetricsStore

PKG = pathlib.Path(__file__).resolve().parents[1] / "src" / "franklinwh_direct_connect_bridge"
TZ = dt.timezone(dt.timedelta(hours=11))
NOW = dt.datetime(2026, 11, 17, 0, 20, tzinfo=TZ).timestamp()        # Sydney, off-peak

TOU = {"seasons": [{"id": "all", "months": list(range(1, 13)),
                    "time_periods": {"off_peak": {"buy": 0.20, "sell": 0.05},
                                     "on_peak": {"buy": 0.50, "sell": 0.05}},
                    "blocks": [{"start": "00:00", "end": "15:00", "time_period": "off_peak"},
                               {"start": "15:00", "end": "21:00", "time_period": "on_peak"},
                               {"start": "21:00", "end": "24:00", "time_period": "off_peak"}]}]}


@pytest.fixture
def st(tmp_path, monkeypatch):
    s = MetricsStore(str(tmp_path / "m.db"))
    monkeypatch.setattr(environment, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "_settings", None)
    setup_wizard.set_site_timezone(s, "Australia/Sydney")
    state.reset_gateways()
    gw = state.register_gateway("gw1", "192.0.2.10", "gw1")
    gw.last_summary = {"power": {"soc": 20, "mode": "Time-of-Use", "off_grid": False}}
    monkeypatch.setattr(system_setup, "cached_capacity_kwh", lambda *a, **k: 13.6)
    smart_dispatch._cache.clear()
    load_forecast._models.clear()           # fitted once a site day per gateway
    yield s
    state.reset_gateways()
    s.close()


def tariff(s, pricing=TOU):
    s.create_site(sid="s1", name="Home", is_default=True)
    s.create_meter(mid="m1", site_id="s1", name="Meter 1", is_default=True)
    s.create_gateway(gw_id="gw1", label="A", is_mock=True, is_default=True)
    s.update_gateway("gw1", meter_id="m1")
    s.create_utility(uid="u1", name="Example")
    s.create_tariff(tid="t1", utility_id="u1", name="TOU", meter_id="m1",
                    effective_start="2026-01-01", pricing=pricing)
    s.update_meter("m1", utility_id="u1", tariff_id="t1")


def seed_load(s, days=14):
    start = int(NOW) // 3600 * 3600 - days * 86400
    for t in range(start, int(NOW), 900):
        s.insert({"load_w": 1000}, t, gateway_id="gw1")


def test_without_a_plan_it_asks_for_one_and_plans_nothing(st):
    r = smart_dispatch.view(st, None, "gw1", NOW)
    assert [m["key"] for m in r["missing"]] == ["plan"]
    assert r["result"] is None and r["decision"] is None
    assert r["questions"][0]["key"] == "objective"


def test_a_utility_plan_asks_the_target_and_limits_to_confirm(st):
    tariff(st)
    r = smart_dispatch.view(st, None, "gw1", NOW)
    qs = {q["key"]: q for q in r["questions"]}
    assert qs["objective"]["value"] == "tou" and qs["objective"]["please_confirm"]
    assert qs["grid_charge"]["value"] == "prohibited"
    assert {c["value"] for c in qs["grid_charge"]["choices"]} == {"allowed", "limited",
                                                                   "prohibited"}
    assert "export" in qs and "demand_aware" not in qs          # two-way, no demand charge
    assert r["facts"]["tou_bands"] and r["plan_name"]


def test_the_plan_charges_off_peak_when_grid_charging_is_allowed(st):
    tariff(st)
    seed_load(st)
    smart_dispatch.save(st, "gw1", {"objective": "lowest_cost", "grid_charge": "allowed"})
    r = smart_dispatch.view(st, None, "gw1", NOW)
    assert not r["missing"] and not r["issues"]
    steps = r["result"]["steps"]
    assert len(steps) == 48
    assert "charge" in [s["action"] for s in steps]
    assert r["result"]["saving"] > 0
    assert r["decision"]["action"] in ("charge", "self", "hold")
    assert r["controls"] is False
    qs = {q["key"]: q for q in r["questions"]}
    assert qs["grid_charge"]["please_confirm"] is False


def test_it_never_writes_to_the_gateway(st, monkeypatch):
    tariff(st)
    seed_load(st)
    def boom(*a, **k):
        raise AssertionError("Smart Dispatch phase 1 must not write")
    monkeypatch.setattr(battery_control, "execute", boom)
    smart_dispatch.save(st, "gw1", {"grid_charge": "allowed"})
    assert smart_dispatch.view(st, None, "gw1", NOW, force=True)["result"]


def test_emergency_backup_on_the_gateway_is_noted(st):
    tariff(st)
    state.get_gateway("gw1").last_summary["power"]["mode"] = "Emergency Backup"
    r = smart_dispatch.view(st, None, "gw1", NOW)
    assert any("Emergency Backup" in a for a in r["result"]["assumptions"])


def test_off_grid_plans_no_grid_actions(st):
    tariff(st)
    state.get_gateway("gw1").last_summary["power"]["off_grid"] = True
    r = smart_dispatch.view(st, None, "gw1", NOW)
    assert {s["action"] for s in r["result"]["steps"]} == {"self"}


def test_unsaved_answers_are_checked_and_unknown_fields_refused(st):
    tariff(st)
    r = smart_dispatch.view(st, None, "gw1", NOW, answers={"grid_charge": "limited"})
    assert any("grid_charge_kw" in i for i in r["issues"]) and r["result"] is None
    with pytest.raises(ValueError):
        smart_dispatch.save(st, "gw1", {"nope": 1})


def test_the_api_the_tab_and_its_access(st, monkeypatch):
    tariff(st)
    monkeypatch.setattr(db, "get_store", lambda *a, **k: st)
    c = TestClient(app_module.create_app())
    q = {"gateway": "gw1"}
    assert c.get("/api/smart-dispatch", params=q).status_code == 200
    r = c.put("/api/smart-dispatch", params=q, json={"objective": "self_consumption"})
    assert r.status_code == 200
    assert {x["key"]: x for x in r.json()["questions"]}["objective"]["value"] == "self_consumption"
    assert c.put("/api/smart-dispatch", params=q, json={"x": 1}).status_code == 422
    chk = c.post("/api/smart-dispatch/check", params=q, json={"grid_charge": "limited"})
    assert chk.status_code == 200 and chk.json()["issues"]
    assert c.get("/api/smart-dispatch", params={**q, "refresh": 1}).status_code == 200
    assert "smart_dispatch" in tab_access.TABS
    assert tab_access.read_allowed(["smart_dispatch"], "/api/smart-dispatch")
    html = (PKG / "templates" / "tabs" / "smart_dispatch.html").read_text()
    for tid in ("sd-decision", "sd-questions", "sd-chart", "sd-steps", "sd-missing",
                "sd-reevaluate"):
        assert f'data-testid="{tid}"' in html, tid
    assert "Please confirm" in html
    idx = (PKG / "templates" / "index.html").read_text()
    assert 'tabs/smart_dispatch.html' in idx and "smart_dispatch_tab.js" in idx
