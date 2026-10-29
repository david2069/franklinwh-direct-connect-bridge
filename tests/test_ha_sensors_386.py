"""#386 batch 1: Home Assistant sensors from reads every poll already makes.

Grid Status, Active Reserve SOC, Firmware Version and the four 1707 relays. No new aGate
read: each comes from the poll summary the poller already has.
"""
import pytest

from franklinwh_direct_connect_bridge.publish import entities


def _summary(**power):
    return {"power": power}


@pytest.mark.parametrize("off_grid,kind,want", [
    (False, None, "Connected"),
    (True, "simulated", "SimulatedOffGrid"),
    (True, "outage", "Outage"),
    (True, None, "OffGrid"),                # islanded, 1723 not read: cause unknown
])
def test_grid_status_from_off_grid_and_its_kind(off_grid, kind, want):
    st = entities.state_payload(_summary(off_grid=off_grid, off_grid_kind=kind))
    assert st["status_grid_status"] == want
    opts = next(e for e in entities.ENTITIES if e["key"] == "status_grid_status")["options"]
    assert want in opts


def test_grid_status_absent_when_off_grid_unknown():
    assert "status_grid_status" not in entities.state_payload(_summary(soc=50))


def test_active_reserve_is_the_active_modes_reserve():
    st = entities.state_payload({"power": {}, "mode": {"modes": [
        {"name": "Time-of-Use", "reserved_soc": 20, "active": False},
        {"name": "Self-Consumption", "reserved_soc": 35, "active": True}]}})
    assert st["active_reserve_pct"] == 35


def test_firmware_from_the_login_manifest():
    st = entities.state_payload({"power": {}, "firmware": {"IBG_VER": "V12R02B60D00"}})
    assert st["device_firmware"] == "V12R02B60D00"


def test_relays_raw_1_is_on():
    """raw 1 is FranklinWH's OPEN, which conducts; mainRelay1Status read 0 through a real
    island (docs/OFFGRID_DESIGN.md)."""
    st = entities.state_payload({"power": {}, "relays": {
        "mainRelay1Status": 1, "mainRelay2Status": 0, "gridRelay2": 1, "blackStartRelay": 0}})
    assert (st["relay_main1"], st["relay_main2"], st["relay_grid2"],
            st["relay_black_start"]) == ("ON", "OFF", "ON", "OFF")


def test_relays_absent_when_not_read():
    st = entities.state_payload({"power": {}})
    assert not set(entities.RELAY_KEYS.values()) & set(st)


def test_discovery_types_and_enum_options():
    cfgs, _, _ = entities.discovery_configs("n", {}, "p", "d", ["core", "diagnostic"])
    by_topic = dict(cfgs)
    relay = by_topic["d/binary_sensor/n/relay_main1/config"]
    assert relay["device_class"] == "power" and relay["entity_category"] == "diagnostic"
    grid = by_topic["d/sensor/n/status_grid_status/config"]
    assert grid["device_class"] == "enum" and grid["options"][0] == "Connected"
    assert "d/sensor/n/active_reserve_pct/config" in by_topic
    assert "d/sensor/n/device_firmware/config" in by_topic


def test_a_mock_gateway_publishes_no_relays():
    cfgs, _, _ = entities.discovery_configs("n", {}, "p", "d", ["diagnostic"],
                                            skip=entities.MOCK_ABSENT_KEYS)
    assert not any("/relay_" in t for t, _ in cfgs)
