"""#96 — every Home Assistant entity's template key is in the state the poller publishes.

Before 0.4.3 the poller published the raw ``summary["power"]`` dict, while the discovery
templates read the names ``entities.build_state`` produces — a function only the tests
called. 8 of the 21 entities (daily kWh, ambient temperature, battery state) never had a
value in Home Assistant, on real gateways and mocks alike. The old tests passed because
they called ``build_state`` directly; these build the payload the way the POLLER does,
from a real poll of the library's in-process Emulator.
"""
import pytest

from franklinwh_direct_connect_bridge import client, config, mockgw
from franklinwh_direct_connect_bridge.publish import entities

#: Every control's state key is now in the poll (C1 added the 1409 circuit read).
NOT_IN_POLL: set = set()


@pytest.fixture
def mock_summary():
    host = mockgw.start_mock("t96", seed=4242, units=1)
    try:
        yield client.summary(config.get_settings(), host, mock=True)
    finally:
        mockgw.stop_mock("t96")


def test_the_poll_succeeds(mock_summary):
    assert mock_summary.get("ok") is True, mock_summary.get("error")


def test_every_sensor_template_key_is_published(mock_summary):
    st = entities.state_payload(mock_summary)
    # A mock publishes no network (#134) or relay (#386) entities: no source.
    missing = [e["key"] for e in entities.ENTITIES
               if e["key"] not in st and e["key"] not in entities.MOCK_ABSENT_KEYS]
    assert not missing, f"entities whose template key is never published: {missing}"


def test_published_values_are_real_values_not_none(mock_summary):
    """A key that is present but always None is the same defect in disguise."""
    st = entities.state_payload(mock_summary)
    nones = [e["key"] for e in entities.ENTITIES
             if st.get(e["key"]) is None and e["key"] not in entities.MOCK_ABSENT_KEYS]
    assert not nones, f"published as null: {nones}"


def test_every_control_state_key_is_published_except_the_unpolled_circuits(mock_summary):
    st = entities.state_payload(mock_summary)
    missing = [c["state_key"] for c in entities.CONTROLS
               if c["state_key"] not in st and c["state_key"] not in NOT_IN_POLL]
    assert not missing


def test_daily_energy_maps_from_the_raw_counters():
    st = entities.state_payload({"power": {"kwh_sun": 22.4, "kwh_uti_in": 0.04,
                                           "kwh_uti_out": 4.7, "kwh_fhp_chg": 11.8,
                                           "kwh_fhp_di": 1.3, "kwh_load": 5.8,
                                           "battery_w": -1500},
                                 "battery": {"t_amb": 27.3}, "latency_ms": 12})
    assert st["solar_today_kwh"] == 22.4 and st["grid_export_today_kwh"] == 4.7
    assert st["battery_charge_today_kwh"] == 11.8 and st["load_today_kwh"] == 5.8
    assert st["ambient_temp_c"] == 27.3 and st["battery_status"] == "charging"
    assert st["kwh_sun"] == 22.4          # raw keys kept for the bridge's own UI


def test_unknown_values_stay_absent_rather_than_invented():
    st = entities.state_payload({"power": {}, "latency_ms": None})
    assert "ambient_temp_c" not in st and "battery_status" not in st


def test_circuit_state_follows_sw_mode():
    st = entities.state_payload({"power": {}, "circuits_on": {1: True, 2: False}})
    assert st["circuit_1_on"] is True and st["circuit_2_on"] is False
    assert "circuit_3_on" not in st        # a circuit the gateway does not report stays absent


def test_switch_state_matches_the_discovery_payload():
    """HA renders a JSON true through value_template as "True" — what state_on expects."""
    import json
    cfgs = dict(entities.discovery_configs("n1", entities.device_info("n1", "SN1"),
                                           "franklinwh-local", "homeassistant", None)[0])
    sw = [c for t, c in cfgs.items() if "/switch/" in t][0]
    assert sw["state_on"] == "True" and sw["state_off"] == "False"
    assert json.loads(json.dumps({"circuit_1_on": True}))["circuit_1_on"] is True


def test_numeric_sensors_carry_a_display_precision():
    """#114: a real aGate's SoC (99.789474) showed every digit in HA."""
    cfgs = {t.split("/")[-2]: c
            for t, c in entities.discovery_configs("n1", entities.device_info("n1", "SN1"),
                                                   "franklinwh-local", "homeassistant", None)[0]
            if "/sensor/" in t}
    assert cfgs["soc"]["suggested_display_precision"] == 1
    assert cfgs["grid_w"]["suggested_display_precision"] == 0
    assert cfgs["solar_today_kwh"]["suggested_display_precision"] == 2
    assert cfgs["ambient_temp_c"]["suggested_display_precision"] == 1
    assert "suggested_display_precision" not in cfgs["mode"]          # text
    assert "suggested_display_precision" not in cfgs["battery_status"]  # text


def test_diagnostic_entities_land_on_the_diagnostic_card():
    """#121: HA groups by entity_category; the Modbus Bridge puts diagnostics there."""
    cfgs = {t.split("/")[-2]: c
            for t, c in entities.discovery_configs("n1", entities.device_info("n1", "SN1"),
                                                   "franklinwh-local", "homeassistant", None)[0]}
    diag = {e["key"] for e in entities.ENTITIES if e.get("group") == "diagnostic"}
    assert diag >= {"latency_ms", "ambient_temp_c", "run_status"}
    for k in diag:
        assert cfgs[k]["entity_category"] == "diagnostic", k
    assert "entity_category" not in cfgs["soc"]              # main sensors stay sensors
    assert "entity_category" not in cfgs["operating_mode"]   # controls stay controls
