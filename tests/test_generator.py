"""Generator view-model + endpoints (cmdType 1901).

Fixture is the real 1901 payload captured 2026-09-13 from a gateway with NO
generator installed — the case that matters, since the gateway returns the block
regardless and the tab must not present stored defaults as a live generator.
"""
import pytest
from fastapi.testclient import TestClient

from franklinwh_local_bridge import generator
from franklinwh_local_bridge.app import create_app

NO_GEN = {
    "opt": 0, "result": 0, "reason": 0,
    "genEn": 0, "gridVoltCheck": 3, "mode": 2, "genModel": "", "genRatedPower": 0,
    "genOptiPPoint": 70, "startDelTime": 1800, "genStartElec": 20,
    "genCloseElec": 80, "genStat": 0, "manuSw": 0,
    "power": 0, "curr": 0, "volt": 2, "freq": 499, "genpowerGen": 0,
    "charge1En": 1, "charge1StartTime": "11:00", "charge1EndTime": "23:59",
    "charge2En": 0, "charge2StartTime": "00:00", "charge2EndTime": "00:00",
    "charge3En": 0, "charge3StartTime": "00:00", "charge3EndTime": "00:00",
    "oilmanoEn": 0, "manoFre": 7, "manoDate": 0, "manoStartTime": "",
    "manoTime": 5, "manoManExit": 0,
}
RUNNING = {**NO_GEN, "genEn": 1, "genModel": "GenX 7kW", "genRatedPower": 7000,
           "genStat": 1, "manuSw": 1, "genpowerGen": 3200}


def test_absent_generator_is_detected_as_absent():
    assert generator.installed(NO_GEN) is False
    assert generator.build(NO_GEN)["installed"] is False


def test_installed_generator_is_detected():
    v = generator.build(RUNNING)
    assert v["installed"] and v["running"] and v["power_w"] == 3200
    assert v["state_name"] == "Running / ON" and v["mode_name"] == "Auto-schedule"


def test_shared_electricals_are_not_reported_as_generator_output():
    """power/curr/volt/freq are byte-identical in 1411 — gateway-level, not gen."""
    v = generator.build(NO_GEN)
    assert v["power_w"] == NO_GEN["genpowerGen"]
    for leaked in ("curr", "volt", "freq"):
        assert leaked not in v


def test_unset_mode_is_not_guessed():
    """Cloud documents manuSw 1 and 2 only; 0 is observed and must not be invented."""
    assert generator.build(NO_GEN)["mode_name"] == "Unset"


def test_fault_state_flagged():
    assert generator.build({**NO_GEN, "genStat": 3})["fault"] is True


def test_charge_windows_parsed_and_kept_separate():
    w = generator.build(NO_GEN)["charge_windows"]
    assert len(w) == 3
    assert w[0] == {"index": 1, "enabled": True, "start": "11:00", "end": "23:59"}
    assert w[1]["enabled"] is False


def test_maintenance_block():
    m = generator.build(NO_GEN)["maintenance"]
    assert m["every_days"] == 7 and m["run_minutes"] == 5 and m["start"] is None


# ── endpoints ────────────────────────────────────────────────────────────────
@pytest.fixture()
def client(monkeypatch):
    from franklinwh_local_bridge import client as c
    monkeypatch.setattr(c, "generator", lambda s, host=None: generator.build(NO_GEN))
    return TestClient(create_app())


def test_api_generator(client):
    body = client.get("/api/generator").json()
    assert body["installed"] is False and body["soc_start_pct"] == 20


def test_mode_write_refuses_when_no_generator(monkeypatch):
    """An unexercised write must not be fired at hardware that isn't there."""
    from franklinwh_local_bridge import client as c
    monkeypatch.setattr(c, "writes_enabled", lambda s: True)

    def boom(s, mode, host=None):
        raise c.NotInstalledError("no generator detected")
    monkeypatch.setattr(c, "set_generator_mode", boom)
    r = TestClient(create_app()).post("/api/generator/mode", json={"mode": "auto"})
    assert r.status_code == 409


def test_invalid_mode_rejected():
    from franklinwh_local_bridge import client as c
    from franklinwh_local_bridge.config import Settings
    with pytest.raises(ValueError):
        c.set_generator_mode(Settings(), "turbo")


# ── config write endpoints (1901, hardware-verified) ─────────────────────────
def test_window_endpoint_delegates(monkeypatch):
    from franklinwh_local_bridge import client as c
    monkeypatch.setattr(c, "writes_enabled", lambda s: True)
    seen = {}

    def fake(s, window, enabled, start, end, host=None):
        seen.update(window=window, enabled=enabled, start=start, end=end)
        return {"ok": True, "confirmed": True}
    monkeypatch.setattr(c, "set_generator_window", fake)
    r = TestClient(create_app()).put(
        "/api/generator/window/2", json={"enabled": True, "start": "02:00", "end": "03:30"})
    assert r.status_code == 200 and r.json()["ok"] is True
    assert seen == {"window": 2, "enabled": True, "start": "02:00", "end": "03:30"}


def test_soc_endpoint_rejects_inverted_thresholds(monkeypatch):
    from franklinwh_local_bridge import client as c
    monkeypatch.setattr(c, "writes_enabled", lambda s: True)

    def fake(s, start_below, stop_above, host=None):
        raise ValueError("stop_above must exceed start_below")
    monkeypatch.setattr(c, "set_generator_soc", fake)
    r = TestClient(create_app()).put("/api/generator/soc",
                                     json={"start_below": 80, "stop_above": 20})
    assert r.status_code == 422


def test_exercise_endpoint_drops_unset_fields(monkeypatch):
    """Only the fields the user actually edited are sent."""
    from franklinwh_local_bridge import client as c
    monkeypatch.setattr(c, "writes_enabled", lambda s: True)
    seen = {}

    def fake(s, host=None, **changes):
        seen.update(changes)
        return {"ok": True}
    monkeypatch.setattr(c, "set_generator_exercise", fake)
    TestClient(create_app()).put("/api/generator/exercise",
                                 json={"every_days": 14, "minutes": 9})
    assert seen == {"every_days": 14, "minutes": 9}


def test_circuits_raw_endpoint_exists(monkeypatch):
    """Smart Circuits gained the Raw JSON button Generator already had."""
    from franklinwh_local_bridge import client as c
    monkeypatch.setattr(c, "read", lambda s, name, host=None: {"SwMerge": 0})
    r = TestClient(create_app()).get("/api/circuits/raw")
    assert r.status_code == 200 and r.json() == {"SwMerge": 0}


# ── enabled vs installed: the gate on editing ────────────────────────────────
def test_enabled_and_configured_are_distinct_facts():
    """genEn is a feature flag; hardware evidence is separate. The official app
    lets you enable the feature with no module fitted, and so does the protocol."""
    assert generator.enabled({"genEn": 1}) is True
    assert generator.configured({"genEn": 1}) is False          # flag proves nothing
    assert generator.configured({"genModel": "GenX 7kW"}) is True
    assert generator.enabled({"genModel": "GenX 7kW"}) is False  # hardware, switched off


def test_config_is_not_editable_while_disabled():
    """The gateway accepts these writes either way — the UI must not imply they act."""
    assert generator.build(NO_GEN)["editable"] is False
    assert generator.build({**NO_GEN, "genEn": 1})["editable"] is True


def test_hardware_present_but_disabled_is_still_not_editable():
    v = generator.build({**NO_GEN, "genModel": "GenX 7kW", "genRatedPower": 7000})
    assert v["configured"] is True and v["enabled"] is False and v["editable"] is False


def test_enable_endpoint_delegates(monkeypatch):
    from franklinwh_local_bridge import client as c
    monkeypatch.setattr(c, "writes_enabled", lambda s: True)
    seen = {}

    def fake(s, on, host=None):
        seen["on"] = on
        return {"ok": True, "confirmed": True, "after": {"genEn": 1}}
    monkeypatch.setattr(c, "set_generator_enabled", fake)
    r = TestClient(create_app()).put("/api/generator/enable", json={"enabled": True})
    assert r.status_code == 200 and seen["on"] is True


def test_enable_succeeds_without_hardware_by_design():
    """Unlike set_generator_mode, enabling must NOT refuse when nothing is fitted —
    that is what the official app does, and refusing would block a real install."""
    import inspect
    from franklinwh_local_bridge import client as c
    assert "NotInstalledError" not in inspect.getsource(c.set_generator_enabled)
