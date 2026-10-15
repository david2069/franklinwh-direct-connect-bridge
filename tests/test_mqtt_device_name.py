"""The Home Assistant device is named after the gateway it is.

Owner, 2026-10-15: the device should read "FranklinWH Direct <last 8 of the serial>". It
was the fixed string "FranklinWH aGate (Local Bridge)", so every gateway on a multi-gateway
site produced a device with the SAME name and the only way to tell them apart in Home
Assistant was to open each one.

The rename is safe because Home Assistant keys a device on its IDENTIFIERS, not its name:
a renamed device is the same device with a new label, and its entities, ids and history all
survive. Changing the identifiers would do the opposite, and these tests pin that they do
not change.
"""
from franklinwh_direct_connect_bridge.publish import entities, mqtt_scan

SERIAL = "10060006A02F24170091"      # pii: allow — documentation placeholder


def test_the_device_is_named_after_the_serial_tail():
    assert entities.device_name(SERIAL) == "FranklinWH Direct 24170091"


def test_two_gateways_get_two_distinguishable_names():
    other = "10060006A02F24170092"   # pii: allow — documentation placeholder
    assert entities.device_name(SERIAL) != entities.device_name(other)


def test_no_serial_still_gives_a_usable_name():
    """A gateway whose serial has not been read yet must not produce 'FranklinWH Direct '."""
    assert entities.device_name("") == "FranklinWH Direct Connect"
    assert entities.device_name(None) == "FranklinWH Direct Connect"


def test_the_identifiers_do_not_change_with_the_name():
    """THE thing that must not move: identifiers are the device's identity in HA."""
    d = entities.device_info("abc123", SERIAL)
    assert d["identifiers"] == ["franklinwh_abc123"]
    assert d["name"] == "FranklinWH Direct 24170091"
    assert d["serial_number"] == SERIAL


def test_our_own_entities_are_still_recognised_as_ours():
    """Ownership on a shared broker is decided by the sw_version prefix."""
    d = entities.device_info("abc123", SERIAL, firmware="V12R02B30D06")
    assert d["sw_version"].startswith(mqtt_scan.OWN_SW_PREFIX)
    assert mqtt_scan._is_ours(d["sw_version"]) is True


def test_entities_published_by_an_older_version_are_still_ours():
    """Discovery configs are RETAINED, so the old wording survives until a republish. A
    purge that stopped recognising it would walk past its own leftovers."""
    assert mqtt_scan._is_ours("Local Bridge v0.2.0 · aGate V12R02B30D06") is True
    assert mqtt_scan._is_ours("Direct Connect Bridge v0.3.3") is True


def test_another_integrations_entities_are_never_ours():
    for foreign in ("FranklinWH Modbus Bridge v1.2", "FWHAI 0.9", "", None):
        assert mqtt_scan._is_ours(foreign) is False
