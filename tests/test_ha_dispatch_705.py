"""#705: a battery dispatch control in Home Assistant, matching the Modbus Bridge (owner
2026-11-17): Battery Command, Command Power, Command Power %, Command Duration and Target
SoC, with its names, options and ranges. They run the Battery tab's Battery Command
(battery_control over the Modbus TCP Server), share its staged values, and are gated by
allow_writes and the Controls group like every other control.
"""
import pathlib

import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import app as app_module
from franklinwh_direct_connect_bridge import battery_control, config, state
from franklinwh_direct_connect_bridge.publish import entities, handle_command

PKG = pathlib.Path(__file__).resolve().parents[1] / "src" / "franklinwh_direct_connect_bridge"
CTRL = {c["key"]: c for c in entities.CONTROLS}
KEYS = ("battery_command", "battery_command_power", "battery_command_power_pct",
        "battery_command_duration", "battery_command_target_soc")


@pytest.fixture(autouse=True)
def _fresh():
    battery_control.reset_staged()
    yield
    battery_control.reset_staged()


def test_the_modbus_bridges_entities():
    bc = CTRL["battery_command"]
    assert (bc["name"], bc["ha_type"]) == ("Battery Command", "select")
    assert bc["options"] == ["Not Active", "Force Charge", "Force Discharge",
                             "Force Standby", "Release"]
    want = {
        "battery_command_power": ("Command Power", "W", 0, 5000, 100),
        "battery_command_power_pct": ("Command Power %", "%", 0, 100, 5),
        "battery_command_duration": ("Command Duration", "s", 0, 7200, 60),
        "battery_command_target_soc": ("Target SoC", "%", 0, 100, 5),
    }
    for key, (name, unit, lo, hi, step) in want.items():
        c = CTRL[key]
        assert (c["name"], c["ha_type"], c["unit"], c["min"], c["max"], c["step"]) == \
            (name, "number", unit, lo, hi, step), key


def test_discovery_carries_each_numbers_range_and_unit():
    cfgs = dict(entities.discovery_configs("n", {}, "p", "d", ["controls"])[0])
    pw = cfgs["d/number/n/battery_command_power/config"]
    assert (pw["min"], pw["max"], pw["step"], pw["unit_of_measurement"]) == (0, 5000, 100, "W")
    assert pw["device_class"] == "power"
    du = cfgs["d/number/n/battery_command_duration/config"]
    assert (du["max"], du["step"], du["unit_of_measurement"], du["device_class"]) == \
        (7200, 60, "s", "duration")
    sel = cfgs["d/select/n/battery_command/config"]
    assert sel["options"][0] == "Not Active"
    assert sel["command_topic"] == "p/n/control/battery_command/set"
    # the reserve numbers keep their 0-100 % in steps of 1
    rs = cfgs["d/number/n/reserve_soc_tou/config"]
    assert (rs["min"], rs["max"], rs["step"], rs["unit_of_measurement"]) == (0, 100, 1, "%")
    # nothing without the Controls group
    none = dict(entities.discovery_configs("n", {}, "p", "d", ["core"])[0])
    assert not any("battery_command" in t for t in none)


def test_a_mock_gateway_has_none_of_them():
    """battery_control refuses a mock (no Modbus TCP Server): a control that can never
    work is not published."""
    assert set(KEYS) <= entities.MOCK_ABSENT_KEYS


def test_staging_from_ha_is_the_battery_tabs_staging():
    for key, payload, field, want in (("battery_command_power", "2500", "power_w", 2500),
                                      ("battery_command_power_pct", "40", "power_pct", 40),
                                      ("battery_command_duration", "1800", "duration_s", 1800),
                                      ("battery_command_target_soc", "80", "target_soc", 80)):
        out = handle_command(key, payload, settings=config.get_settings(), client=None,
                             host="192.0.2.10")
        assert battery_control.STAGED[field] == want, out
    assert battery_control.STAGED["power_mode"] == "pct"     # last set wins, as the tab
    handle_command("battery_command_power", "1000", settings=config.get_settings(),
                   client=None, host="192.0.2.10")
    assert battery_control.STAGED["power_mode"] == "w"


def test_battery_command_runs_the_battery_tabs_command(monkeypatch):
    seen = {}

    def fake_run(value, **kw):
        seen.update(kw, value=value)
        return {"ok": True, "result": "sent", "active": value}

    monkeypatch.setattr(battery_control, "run_command", fake_run)
    gw = type("G", (), {"id": "gw1", "last_state": {"soc": 55}})()
    out = handle_command("battery_command", "Force Charge", settings=config.get_settings(),
                         client=None, host="192.0.2.10", gateway=gw)
    assert seen["value"] == "Force Charge" and seen["host"] == "192.0.2.10"
    assert seen["gateway_id"] == "gw1" and seen["source"] == "ha"
    assert seen["soc_getter"]() == 55
    assert "sent" in out
    assert "unknown" in handle_command("battery_command", "Force Fly",
                                       settings=config.get_settings(), client=None,
                                       host="192.0.2.10", gateway=gw)


def test_run_command_records_a_home_assistant_force(monkeypatch):
    monkeypatch.setattr(battery_control, "execute",
                        lambda *a, **k: {"ok": True, "result": "ok", "active": "Force Discharge"})
    rec = {}

    class Store:
        def record_dispatch(self, **kw):
            rec.update(kw)

        def log_schedule_event(self, *a, **k):
            pass

    battery_control.stage("battery_command_power", 1500)
    out = battery_control.run_command("Force Discharge", host="192.0.2.10", gateway_id="gw1",
                                      soc_getter=lambda: 50, store=Store(), source="ha")
    assert out["ok"] and battery_control.STAGED["active"] == "Force Discharge"
    assert rec["name"] == "Battery Control (Home Assistant)" and rec["watts"] == -1500
    assert rec["schedule_id"] == "_widget" and rec["gateway_id"] == "gw1"


def test_ha_state_reports_the_held_force_and_the_staged_values(monkeypatch):
    monkeypatch.setattr(battery_control, "current",
                        lambda host=None: {"active": "Force Charge"})
    battery_control.stage("battery_command_duration", 900)
    st = battery_control.ha_state("192.0.2.10")
    assert st == {"battery_command_state": "Force Charge", "battery_command_power_w": 0,
                  "battery_command_power_pct": 100, "battery_command_duration_s": 900,
                  "battery_command_target_soc": 0}
    for c in entities.CONTROLS:
        if c["key"] in KEYS:
            assert c["state_key"] in st, c["key"]


def test_the_battery_tab_sees_values_staged_in_ha(monkeypatch):
    state.reset_gateways()
    state.register_gateway("gw1", "192.0.2.10", "House")
    try:
        c = TestClient(app_module.create_app())
        handle_command("battery_command_power", "3000", settings=config.get_settings(),
                       client=None, host="192.0.2.10")
        monkeypatch.setattr(battery_control, "status", lambda host: {"available": False})
        got = c.get("/api/battery/command?gateway=gw1").json()
        assert got["power_w"] == 3000 and got["power_mode"] == "w"
    finally:
        state.reset_gateways()


def test_the_poller_publishes_the_state_and_republishes_after_a_control():
    src = (PKG / "poller.py").read_text()
    assert src.count("_bc.ha_state(") >= 2
