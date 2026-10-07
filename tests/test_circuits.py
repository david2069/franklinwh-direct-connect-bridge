"""Smart circuits — presence detection, view-model and endpoints.

Fixtures are the REAL 1409/1411 payloads captured from the AU aGate on 2026-09-13,
trimmed to the fields under test. The AU case is the interesting one: the firmware
reports a full Sw3 block for a circuit that does not physically exist.
"""
import json

import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import circuits
from franklinwh_direct_connect_bridge.app import create_app

# Real capture: Sw1 named+scheduled, Sw2 renamed+scheduled, Sw3 factory defaults.
AU_CFG = {
    "SwMerge": 0,
    "Sw1Name": "Circuit 1", "Sw1Mode": 0, "Sw1ProLoad": 0, "Sw1SocLowSet": 53,
    "Sw1AtuoEn": 0, "Sw1TimeEn": [1, 1, 0, 0], "Sw1TimeSet": [1, 0, 1, 0],
    "Sw1Time": ["2026-06-19 16:02", "2026-06-19 17:03",
                "2026-06-19 20:11", "2026-06-19 20:12"],
    "Sw2Name": "Test Switch", "Sw2Mode": 0, "Sw2SocLowSet": 0, "Sw2AtuoEn": 0,
    "Sw2TimeEn": [0, 0, 0, 0], "Sw2TimeSet": [1, 0, 1, 0],
    "Sw2Time": ["2026-05-16 04:30", "2026-05-16 05:30",
                "2026-05-16 12:00", "2026-05-16 13:30"],
    "Sw3Name": "Circuits 3", "Sw3Mode": 0, "Sw3SocLowSet": 20, "Sw3AtuoEn": 0,
    "Sw3TimeEn": [0, 0, 0, 0], "Sw3TimeSet": [0, 0, 0, 0],
    "Sw3Time": ["2000-01-01 00:00", "2000-01-01 23:59",
                "2000-01-01 00:00", "2000-01-01 23:59"],
    "CarSwConsSupEnable": 0,
}
AU_METER = {
    "Sw1Volt": 1020, "Sw2Volt": 0,
    "SW1Curr": 0, "SW2Curr": 0, "SW1ExpPower": 0, "SW2ExpPower": 0,
    "SW1ExpEnergy": 0, "SW2ExpEnergy": 0,
    "CarSWCurr": 1, "CarSWPower": -3,
    "CarSWExpEnergy": 10077, "CarSWImpEnergy": 15458,
    "freq": 499,
}


# ── detection ────────────────────────────────────────────────────────────────
def test_au_gateway_detects_two_circuits():
    v = circuits.build(AU_CFG, AU_METER)
    assert v["count"] == 2
    assert [c["present"] for c in v["circuits"]] == [True, True, False]


def test_absent_circuit_is_returned_not_dropped():
    """Hiding it loses the distinction between 'no circuit' and 'read failed'."""
    v = circuits.build(AU_CFG, AU_METER)
    assert len(v["circuits"]) == 3
    third = v["circuits"][2]
    assert third["present"] is False
    assert third["evidence_against"]      # must say why


def test_factory_placeholder_schedule_is_not_a_schedule():
    assert circuits.schedule_slots(AU_CFG, 3) == [] or \
        all(s["at"] is None for s in circuits.schedule_slots(AU_CFG, 3))
    assert any(s["at"] for s in circuits.schedule_slots(AU_CFG, 1))


def test_sw3_keys_present_does_not_imply_a_third_circuit():
    """The bug behind franklinwh-cloud#7 — key presence is not evidence."""
    assert "Sw3Name" in AU_CFG and "Sw3SocLowSet" in AU_CFG
    assert circuits.build(AU_CFG, AU_METER)["circuits"][2]["present"] is False


def test_no_circuits_installed_is_distinct_from_region_count():
    bare = {f"Sw{i}{k}": v for i in (1, 2, 3)
            for k, v in (("Name", f"Circuits {i}"), ("Mode", 0), ("SocLowSet", 20),
                         ("TimeEn", [0] * 4), ("TimeSet", [0] * 4),
                         ("Time", ["2000-01-01 00:00"] * 4))}
    v = circuits.build(bare, {})
    assert v["installed"] is False and v["count"] == 0


def test_setting_pins_the_count_and_says_so():
    v = circuits.build(AU_CFG, AU_METER, override="3")
    assert [c["present"] for c in v["circuits"]] == [True, True, True]
    assert v["source"] == "setting" and v["count"] == 3
    assert circuits.build(AU_CFG, AU_METER, override="0")["installed"] is False


def test_bad_override_falls_back_to_detection():
    v = circuits.build(AU_CFG, AU_METER, override="banana")
    assert v["source"] == "detected" and v["count"] == 2


# ── metering ─────────────────────────────────────────────────────────────────
def test_missing_meter_channel_is_none_not_zero():
    """A real 0 W and 'no such channel' must not look the same."""
    m = circuits.meter(AU_METER, 3)
    assert m["watts"] is None and m["has_meter"] is False
    assert circuits.meter(AU_METER, 1)["watts"] == 0        # a genuine zero


def test_volts_use_the_confirmed_tenths_scale():
    assert circuits.meter(AU_METER, 1)["volts"] == 102.0    # 1020 / 10


def test_carsw_is_separate_from_circuit_three():
    """Cloud calls CarSW 'Sw3'; locally 1409 carries both, so don't conflate."""
    v = circuits.build(AU_CFG, AU_METER)
    assert v["carsw"]["export_lifetime_kwh"] == 100.77
    assert v["circuits"][2]["energy_lifetime_kwh"] is None


def test_energy_is_labelled_lifetime_not_today():
    c = circuits.build(AU_CFG, AU_METER)["circuits"][0]
    assert "energy_lifetime_kwh" in c and "energy_today_kwh" not in c


# ── endpoints ────────────────────────────────────────────────────────────────
@pytest.fixture()
def client(monkeypatch):
    from franklinwh_direct_connect_bridge import client as c
    monkeypatch.setattr(c, "circuits",
                        lambda s, host=None, override="auto":
                        circuits.build(AU_CFG, AU_METER, override))
    return TestClient(create_app())


def test_api_circuits(client):
    r = client.get("/api/circuits")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 2 and len(body["circuits"]) == 3


def test_cloud_parity_endpoint_still_emits_three(monkeypatch):
    """/api/cloud/* mirrors the cloud shape exactly — detection must not leak in."""
    from franklinwh_direct_connect_bridge import client as c
    monkeypatch.setattr(c, "read", lambda s, name, host=None: AU_CFG)
    r = TestClient(create_app()).get("/api/cloud/smart-circuits")
    assert sorted(r.json().keys()) == ["1", "2", "3"]


# ── schedule writing ─────────────────────────────────────────────────────────
def test_schedule_write_builds_pairs_and_preserves_the_date():
    """The date component is when the slot was written, not a one-shot date."""
    patch = circuits.build_schedule_write(
        AU_CFG, 1, [{"enabled": True, "start": "06:30", "end": "09:00"}], "2026-09-14")
    assert patch["Sw1Time"][0] == "2026-06-19 06:30"     # existing date kept
    assert patch["Sw1Time"][1] == "2026-06-19 09:00"
    assert patch["Sw1TimeEn"] == [1, 1, 0, 0]
    assert patch["Sw1TimeSet"] == [1, 0, 1, 0]


def test_placeholder_slot_gets_today_not_the_year_2000():
    patch = circuits.build_schedule_write(
        AU_CFG, 3, [{"enabled": True, "start": "01:00", "end": "02:00"}], "2026-09-14")
    assert patch["Sw3Time"][0] == "2026-09-14 01:00"


def test_end_before_start_rejected():
    with pytest.raises(circuits.ScheduleError):
        circuits.build_schedule_write(
            AU_CFG, 1, [{"enabled": True, "start": "09:00", "end": "06:00"}], "2026-09-14")


def test_equal_start_and_end_rejected():
    with pytest.raises(circuits.ScheduleError):
        circuits.build_schedule_write(
            AU_CFG, 1, [{"enabled": True, "start": "09:00", "end": "09:00"}], "2026-09-14")


def test_overlapping_enabled_windows_rejected():
    """The firmware accepts overlap happily; we do not."""
    with pytest.raises(circuits.ScheduleError):
        circuits.build_schedule_write(AU_CFG, 1, [
            {"enabled": True, "start": "06:00", "end": "10:00"},
            {"enabled": True, "start": "09:00", "end": "11:00"},
        ], "2026-09-14")


def test_disabled_window_may_overlap():
    patch = circuits.build_schedule_write(AU_CFG, 1, [
        {"enabled": True, "start": "06:00", "end": "10:00"},
        {"enabled": False, "start": "09:00", "end": "11:00"},
    ], "2026-09-14")
    assert patch["Sw1TimeEn"] == [1, 1, 0, 0]


def test_bad_time_formats_rejected():
    for bad in ("25:00", "6:70", "morning", "", None):
        with pytest.raises(circuits.ScheduleError):
            circuits.build_schedule_write(
                AU_CFG, 1, [{"enabled": True, "start": bad, "end": "10:00"}], "2026-09-14")


def test_more_than_two_windows_rejected():
    with pytest.raises(circuits.ScheduleError):
        circuits.build_schedule_write(AU_CFG, 1, [
            {"enabled": True, "start": "01:00", "end": "02:00"},
            {"enabled": True, "start": "03:00", "end": "04:00"},
            {"enabled": True, "start": "05:00", "end": "06:00"},
        ], "2026-09-14")


def test_schedule_write_does_not_touch_other_circuits(client):
    """Other circuits' slots must survive — the whole block is rewritten."""
    patch = circuits.build_schedule_write(
        AU_CFG, 1, [{"enabled": True, "start": "06:00", "end": "07:00"}], "2026-09-14")
    assert all(k.startswith("Sw1") for k in patch)


def test_schedule_endpoint_422_on_bad_window(monkeypatch):
    from franklinwh_direct_connect_bridge import client as c
    monkeypatch.setattr(c, "writes_enabled", lambda s: True)

    def boom(s, circuit, windows, today, host=None):
        raise circuits.ScheduleError("end is not after start")
    monkeypatch.setattr(c, "set_circuit_schedule", boom)
    r = TestClient(create_app()).put(
        "/api/circuits/1/schedule",
        json={"windows": [{"enabled": True, "start": "09:00", "end": "06:00"}]})
    assert r.status_code == 422


def test_schedule_write_delegates_to_the_library(monkeypatch):
    """Protocol recipe lives in franklinwh_local; the bridge only maps the shape.

    The discard behaviour itself is pinned in the library's own tests — here we
    check the two-window editor shape becomes the firmware's four slots and that
    the library's verdict is passed through untouched.
    """
    from franklinwh_direct_connect_bridge import client as c
    from franklinwh_direct_connect_bridge.config import Settings

    seen = {}

    class FakeClient:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def login(self): return {}
        def smart_circuits(self): return dict(AU_CFG)

        def set_circuit_schedule(self, circuit, slots, enabled):
            seen.update(circuit=circuit, slots=slots, enabled=enabled)
            return {"ok": False, "result": 0, "discarded": True, "confirmed": False,
                    "note": "discarded on this firmware"}

    monkeypatch.setattr(c, "_client", lambda s, host=None: FakeClient())
    out = c.set_circuit_schedule(
        Settings(), 2, [{"enabled": True, "start": "03:15", "end": "04:45"}],
        "2026-09-14")

    assert seen["circuit"] == 2
    assert seen["enabled"] == [1, 1, 0, 0]          # one window -> two slots
    assert seen["slots"][0].endswith("03:15") and seen["slots"][1].endswith("04:45")
    assert out["result"] == 0                        # device said OK...
    assert out["ok"] is False and out["discarded"] is True     # ...we do not
    assert out["hardware_verified"] is False
