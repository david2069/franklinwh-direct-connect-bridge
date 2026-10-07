"""Writable HA entities — the controls that make the bridges functionally equivalent."""
import pytest

from franklinwh_direct_connect_bridge.publish import entities, handle_command


def test_controls_are_published_with_command_topics():
    cfgs, state_topic, _ = entities.discovery_configs(
        "abc", {}, "franklinwh-local", "homeassistant")
    ctrl = {t: c for t, c in cfgs if "/select/" in t or "/switch/" in t}
    assert len(ctrl) == 4, "operating mode + three smart circuits"
    for _t, c in ctrl.items():
        assert c["command_topic"].endswith("/set")
        assert c["state_topic"] == state_topic


def test_operating_mode_select_offers_the_three_work_modes():
    cfgs, _, _ = entities.discovery_configs("abc", {}, "p", "homeassistant")
    sel = next(c for t, c in cfgs if "/select/" in t)
    assert sel["options"] == ["Time-of-Use", "Self-Consumption", "Emergency Backup"]


def test_mode_maps_to_the_stable_alias_not_the_site_id():
    """Programme ids are site-specific GUIDs and the name can be a tariff, so
    neither travels; scheduling_type (tou/self/backup) does."""
    assert entities.MODE_ALIAS["Time-of-Use"] == "tou"
    assert entities.MODE_ALIAS["Self-Consumption"] == "self"
    assert entities.MODE_ALIAS["Emergency Backup"] == "backup"


def test_command_topic_round_trip():
    f = entities.command_topic_filter("abc", "p")
    assert f == "p/abc/control/+/set"
    assert entities.key_from_command_topic("p/abc/control/smart_circuit_2/set") \
        == "smart_circuit_2"


class _Client:
    def __init__(self): self.calls = []
    def set_mode(self, s, mode, host=None):
        self.calls.append(("mode", mode)); return {"ok": True}
    def set_smart_circuit(self, s, circuit, on, host=None):
        self.calls.append(("circuit", circuit, on)); return {"confirmed": True}


def test_mode_command_routes_to_set_mode():
    c = _Client()
    out = handle_command("operating_mode", "Time-of-Use", settings=None, client=c)
    assert c.calls == [("mode", "tou")] and "ok" in out


def test_switch_command_routes_to_the_right_circuit():
    c = _Client()
    handle_command("smart_circuit_2", "ON", settings=None, client=c)
    assert c.calls == [("circuit", 2, True)]


def test_switch_reports_read_back_not_just_acceptance():
    class NotConfirmed(_Client):
        def set_smart_circuit(self, s, circuit, on, host=None):
            return {"result": 0, "confirmed": False}
    out = handle_command("smart_circuit_1", "ON", settings=None, client=NotConfirmed())
    assert "NOT confirmed" in out, "result:0 alone must never read as success"


def test_unknown_mode_is_rejected_without_calling_the_gateway():
    c = _Client()
    out = handle_command("operating_mode", "0", settings=None, client=c)
    assert "unknown mode" in out and not c.calls, "there is no mode 0"


def test_reserve_soc_and_schedules_are_not_exposed_as_controls():
    """The gateway accepts and discards both, so an HA entity would appear to work
    and would not."""
    keys = {c["key"] for c in entities.CONTROLS}
    assert not any("reserve" in k for k in keys)
    assert not any("schedule" in k for k in keys)


def test_energy_sensors_come_from_the_existing_poll():
    st = entities.build_state(
        {"kwh_sun": 22.4, "kwh_uti_in": 0.04, "kwh_uti_out": 4.7,
         "kwh_fhp_chg": 11.8, "kwh_fhp_di": 1.3, "kwh_load": 5.8, "t_amb": 27.3}, {})
    assert st["solar_today_kwh"] == 22.4 and st["grid_export_today_kwh"] == 4.7
    assert st["ambient_temp_c"] == 27.3
