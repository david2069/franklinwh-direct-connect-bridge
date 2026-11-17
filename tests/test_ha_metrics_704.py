"""#704: Home Assistant gets the readings the bridge already has (owner 2026-11-17).

1. VPP active and the off-grid reason and minutes (every poll).
2. Smart circuits, V2L and the generator (#700's 60 s read, and kWh today from every poll).
4. The gateway's active alarms count.

No reading means the key is left out, so HA shows unknown, never 0.
"""
import pathlib

from franklinwh_direct_connect_bridge import scheduler
from franklinwh_direct_connect_bridge.publish import entities

PKG = pathlib.Path(__file__).resolve().parents[1] / "src" / "franklinwh_direct_connect_bridge"
BY_KEY = {e["key"]: e for e in entities.ENTITIES}


def test_the_new_entities_and_their_groups():
    want = {
        "status_vpp": ("VPP Active", "core", "binary_sensor"),
        "offgrid_reason": ("Off-Grid Reason", "core", "sensor"),
        "offgrid_min": ("Off-Grid Duration", "core", "sensor"),
        "generator_today_kwh": ("Generator Today", "energy", "sensor"),
        "generator_state": ("Generator State", "power", "sensor"),
        "generator_enabled": ("Generator Enabled", "diagnostic", "binary_sensor"),
        "v2l_power_w": ("V2L Power", "power", "sensor"),
        "v2l_export_kwh": ("V2L Export Energy", "energy", "sensor"),
        "v2l_import_kwh": ("V2L Import Energy", "energy", "sensor"),
        "active_alarms": ("Active Alarms", "diagnostic", "sensor"),
    }
    for n in (1, 2, 3):
        want[f"circuit_{n}_power_w"] = (f"Smart Circuit {n} Power", "power", "sensor")
        want[f"circuit_{n}_today_kwh"] = (f"Smart Circuit {n} Energy Today", "energy", "sensor")
    for key, (name, group, ha_type) in want.items():
        e = BY_KEY.get(key)
        assert e, key
        assert (e["name"], e["group"], e.get("ha_type", "sensor")) == (name, group, ha_type), key
    assert BY_KEY["offgrid_min"]["unit"] == "min"
    assert BY_KEY["circuit_1_power_w"]["device_class"] == "power"
    assert BY_KEY["circuit_1_today_kwh"]["state_class"] == "total_increasing"
    assert BY_KEY["v2l_export_kwh"]["state_class"] == "total_increasing"


def test_vpp_and_generator_today_from_the_poll():
    st = entities.state_payload({"power": {"vpp": True, "kwh_gen": 1.25}})
    assert st["status_vpp"] == "ON" and st["generator_today_kwh"] == 1.25
    assert entities.state_payload({"power": {"vpp": False}})["status_vpp"] == "OFF"
    assert "status_vpp" not in entities.state_payload({"power": {"soc": 50}})


def test_off_grid_reason_only_while_off_grid():
    st = entities.state_payload({"power": {"off_grid": True, "off_grid_kind": "simulated"}})
    assert st["offgrid_reason"] == "user requested"
    st = entities.state_payload({"power": {"off_grid": True, "off_grid_kind": "outage"}})
    assert st["offgrid_reason"] == "grid outage"
    st = entities.state_payload({"power": {"off_grid": True}})
    assert st["offgrid_reason"] == "unknown"
    assert "offgrid_reason" not in entities.state_payload({"power": {"off_grid": False}})


def test_off_grid_minutes_and_alarms():
    st = {"off_grid": True, "off_grid_since": 1000.0}
    assert entities.late_state(st, now=1000.0 + 125, alarms=2) == {"offgrid_min": 2,
                                                                  "active_alarms": 2}
    # on grid: no minutes; alarms not read: no count
    assert entities.late_state({"off_grid": False}, now=5.0, alarms=None) == {}
    assert entities.late_state({"off_grid": False}, now=5.0, alarms=0) == {"active_alarms": 0}


def test_circuits_v2l_generator_from_the_device_read():
    summ = {"circuits_on": {1: True}}
    extras = {"meter": {1: {"watts": 420.0}, 2: {"watts": 0.0}},
              "today_kwh": {"1": 1.5},
              "carsw": {"watts": 3200.0, "export_lifetime_kwh": 12.5,
                        "import_lifetime_kwh": 3.0},
              "generator": {"enabled": True, "state": 0, "state_name": "Standby / OFF",
                            "rated_power_w": 8000}}
    out = entities.device_payload(scheduler.device_snapshot(summ, extras))
    assert out["circuit_1_power_w"] == 420.0 and out["circuit_2_power_w"] == 0.0
    assert out["circuit_1_today_kwh"] == 1.5
    assert "circuit_3_power_w" not in out and "circuit_2_today_kwh" not in out
    assert (out["v2l_power_w"], out["v2l_export_kwh"], out["v2l_import_kwh"]) == (3200.0, 12.5, 3.0)
    assert out["generator_state"] == "Standby / OFF" and out["generator_enabled"] == "ON"


def test_nothing_read_publishes_nothing():
    assert entities.device_payload(scheduler.device_snapshot({}, None)) == {}


def test_binary_sensors_and_categories_in_discovery():
    cfgs, _, _ = entities.discovery_configs("n", {}, "p", "d", list(entities.GROUPS))
    by_topic = dict(cfgs)
    assert "d/binary_sensor/n/status_vpp/config" in by_topic
    assert "d/binary_sensor/n/generator_enabled/config" in by_topic
    assert by_topic["d/sensor/n/active_alarms/config"]["entity_category"] == "diagnostic"
    assert by_topic["d/sensor/n/circuit_2_power_w/config"]["unit_of_measurement"] == "W"


def test_the_poller_publishes_them():
    src = (PKG / "poller.py").read_text()
    assert "entities.device_payload(" in src and "entities.late_state(" in src
