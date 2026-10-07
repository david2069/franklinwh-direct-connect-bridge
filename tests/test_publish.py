"""Phase 2 — MQTT/HA discovery payload builders (pure, no broker)."""

from franklinwh_direct_connect_bridge.publish import entities


def test_build_state_maps_power_flow_fields():
    power = {"soc": 55.0, "p_uti": 100, "p_sun": -200, "p_fhp": 300, "p_load": 500,
             "p_gen": 0, "name": "Self-Consumption"}
    state = entities.build_state(power, {"latency_ms": 12.3})
    assert state["soc"] == 55.0
    assert state["grid_w"] == 100 and state["solar_w"] == -200
    assert state["battery_w"] == 300 and state["load_w"] == 500
    assert state["mode"] == "Self-Consumption" and state["latency_ms"] == 12.3


def test_discovery_configs_shape():
    device = entities.device_info("sn123", "10060006A02F24170091", "V12R02B30D06")
    configs, state_topic, avail_topic = entities.discovery_configs(
        "sn123", device, "franklinwh-local", "homeassistant")
    assert state_topic == "franklinwh-local/sn123/state"
    assert avail_topic == "franklinwh-local/sn123/availability"
    # one config per entity, correct discovery topic + value_template + device + availability
    assert len(configs) == len(entities.ENTITIES) + len(entities.CONTROLS), \
        "sensors plus the writable controls"
    by_topic = dict(configs)
    soc_topic = "homeassistant/sensor/sn123/soc/config"
    assert soc_topic in by_topic
    soc = by_topic[soc_topic]
    assert soc["value_template"] == "{{ value_json.soc }}"
    assert soc["unit_of_measurement"] == "%" and soc["device_class"] == "battery"
    assert soc["state_topic"] == state_topic
    assert soc["availability_topic"] == avail_topic
    assert soc["device"]["identifiers"] == ["franklinwh_sn123"]
    # sw_version clearly names THIS integration + the aGate firmware
    assert soc["device"]["sw_version"].startswith("Local Bridge v")
    assert "V12R02B30D06" in soc["device"]["sw_version"]


def test_device_info_optional_fields():
    d = entities.device_info("n", "", None)          # no serial/fw
    assert "serial_number" not in d                   # no serial → omitted
    assert d["sw_version"].startswith("Local Bridge v")  # always names the bridge
    assert d["manufacturer"] == "FranklinWH"
    assert "Local Bridge" in d["name"]
