"""FEAT-SETUP-WIZARD — broker conflict analysis (mqtt_scan.analyze).

Grounded in the real shared-broker finding: on one broker the Modbus bridge names the aGate
`franklinwh_<UPPER serial>` and the Local bridge `franklinwh_<lower serial>` — distinct
identifiers → two HA devices (duplicate, not a topic clash). A TRUE collision is only visible
when a non-self producer has overwritten OUR identifier's retained metadata.
"""
import json

from franklinwh_local_bridge.publish import mqtt_scan


def _cfg(ident, name, sw):
    return json.dumps({"device": {"identifiers": [ident], "name": name, "sw_version": sw}}).encode()


def test_analyze_coexist_duplicate_device():
    own = "franklinwh_10060006a02f24170091"
    msgs = {
        "homeassistant/sensor/a/soc/config": _cfg(own, "FranklinWH aGate (Local Bridge)", "Local Bridge v0.1.0 · aGate X"),
        "homeassistant/sensor/a/pwr/config": _cfg(own, "FranklinWH aGate (Local Bridge)", "Local Bridge v0.1.0 · aGate X"),
        "homeassistant/sensor/b/soc/config": _cfg("franklinwh_10060006A02F24170091", "FranklinWH 24170091", "Modbus Bridge v0.1.0 · aGate X"),
    }
    r = mqtt_scan.analyze(msgs, own, "homeassistant", "10060006a02f24170091")
    assert r["ok"] and r["foreign_count"] == 1 and r["collision"] is False
    self_p = [p for p in r["producers"] if p["is_self"]]
    assert len(self_p) == 1 and self_p[0]["identifier"] == own and self_p[0]["entities"] == 2
    assert r["producers"][0]["is_self"] is True                 # self sorts first


def test_analyze_true_collision_when_foreign_overwrites_our_identifier():
    own = "franklinwh_abc"
    msgs = {"homeassistant/sensor/x/soc/config": _cfg(own, "intruder", "Modbus Bridge v9")}
    r = mqtt_scan.analyze(msgs, own, "homeassistant", "abc")
    assert r["collision"] is True and r["foreign_count"] == 1


def test_analyze_clean_only_self():
    own = "franklinwh_x"
    msgs = {"homeassistant/sensor/x/soc/config": _cfg(own, "me", "Local Bridge v1")}
    r = mqtt_scan.analyze(msgs, own, "homeassistant", "x")
    assert r["foreign_count"] == 0 and r["collision"] is False and len(r["producers"]) == 1


def test_analyze_ignores_unparseable_and_missing_device():
    own = "franklinwh_x"
    msgs = {"homeassistant/sensor/x/soc/config": b"not json",
            "homeassistant/sensor/y/soc/config": json.dumps({"name": "no device block"}).encode()}
    r = mqtt_scan.analyze(msgs, own, "homeassistant", "x")
    # the no-device config groups under "?" as one foreign producer; junk is skipped
    assert r["ok"] and r["collision"] is False
