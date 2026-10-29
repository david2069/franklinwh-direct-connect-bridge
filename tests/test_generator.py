"""Generator view-model + endpoints (cmdType 1901).

Fixture is the real 1901 payload captured 2026-09-13 from a gateway with NO
generator installed — the case that matters, since the gateway returns the block
regardless and the tab must not present stored defaults as a live generator.
"""
import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import generator, state
from franklinwh_direct_connect_bridge.app import create_app

GW = "gw-gen"
G = f"?gateway={GW}"     # every device route names its gateway (#379)


@pytest.fixture(autouse=True)
def _gateway():
    state.register_gateway(GW, "192.0.2.10", "Home")
    yield
    state.unregister_gateway(GW)

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
    assert v["state_name"] == "Running / ON"
    assert v["evidence"]["run_state"] == 1         # evidence, not an "installed" verdict


def test_shared_electricals_are_not_reported_as_generator_output():
    """power/curr/volt/freq are byte-identical in 1411 — gateway-level, not gen."""
    v = generator.build(NO_GEN)
    assert v["power_w"] == NO_GEN["genpowerGen"]
    for leaked in ("curr", "volt", "freq"):
        assert leaked not in v


def test_mode_fields_are_reported_raw_and_never_named():
    """#237: neither ``mode`` nor ``manuSw`` is mapped, so neither gets a name."""
    v = generator.build({**NO_GEN, "mode": 2, "manuSw": 0})
    assert v["mode_raw"] == 2 and v["manuSw_raw"] == 0
    assert "mode_name" not in v and "mode" not in v


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
    from franklinwh_direct_connect_bridge import client as c
    monkeypatch.setattr(c, "generator", lambda s, host=None: generator.build(NO_GEN))
    # GW has a host, so the endpoint reaches the (stubbed) device read.
    return TestClient(create_app())


def test_api_generator(client):
    body = client.get("/api/generator" + G).json()
    assert body["available"] is True
    assert body["installed"] is False and body["soc_start_pct"] == 20


def test_mode_endpoint_writes_nothing(monkeypatch):
    """#237: the Auto/Manual write targeted manuSw (start/stop per the cloud captures).
    The endpoint now refuses before any device I/O, whatever the gateway reports."""
    from franklinwh_direct_connect_bridge import client as c
    monkeypatch.setattr(c, "writes_enabled", lambda s: True)
    calls = []
    monkeypatch.setattr(c, "_client", lambda *a, **kw: calls.append(a) or (_ for _ in ()).throw(AssertionError("device I/O")))
    r = TestClient(create_app()).post("/api/generator/mode" + G, json={"mode": "auto"})
    assert r.status_code == 409 and "#237" in r.json()["detail"]
    assert calls == []


def test_no_code_path_writes_manusw():
    """The only writer of manuSw (client.set_generator_mode) is gone (#237)."""
    import pathlib
    from franklinwh_direct_connect_bridge import client as c
    assert not hasattr(c, "set_generator_mode")
    src = pathlib.Path(c.__file__).read_text()
    assert '"manuSw": want' not in src


# ── config write endpoints (1901, hardware-verified) ─────────────────────────
def test_window_endpoint_delegates(monkeypatch):
    from franklinwh_direct_connect_bridge import client as c
    monkeypatch.setattr(c, "writes_enabled", lambda s: True)
    seen = {}

    def fake(s, window, enabled, start, end, host=None):
        seen.update(window=window, enabled=enabled, start=start, end=end)
        return {"ok": True, "confirmed": True}
    monkeypatch.setattr(c, "set_generator_window", fake)
    r = TestClient(create_app()).put(
        "/api/generator/window/2" + G, json={"enabled": True, "start": "02:00", "end": "03:30"})
    assert r.status_code == 200 and r.json()["ok"] is True
    assert seen == {"window": 2, "enabled": True, "start": "02:00", "end": "03:30"}


def test_soc_endpoint_rejects_inverted_thresholds(monkeypatch):
    from franklinwh_direct_connect_bridge import client as c
    monkeypatch.setattr(c, "writes_enabled", lambda s: True)

    def fake(s, start_below, stop_above, host=None):
        raise ValueError("stop_above must exceed start_below")
    monkeypatch.setattr(c, "set_generator_soc", fake)
    r = TestClient(create_app()).put("/api/generator/soc" + G,
                                     json={"start_below": 80, "stop_above": 20})
    assert r.status_code == 422


def test_exercise_endpoint_drops_unset_fields(monkeypatch):
    """Only the fields the user actually edited are sent."""
    from franklinwh_direct_connect_bridge import client as c
    monkeypatch.setattr(c, "writes_enabled", lambda s: True)
    seen = {}

    def fake(s, host=None, **changes):
        seen.update(changes)
        return {"ok": True}
    monkeypatch.setattr(c, "set_generator_exercise", fake)
    TestClient(create_app()).put("/api/generator/exercise" + G,
                                 json={"every_days": 14, "minutes": 9})
    assert seen == {"every_days": 14, "minutes": 9}


def test_circuits_raw_endpoint_exists(monkeypatch):
    """Smart Circuits gained the Raw JSON button Generator already had."""
    from franklinwh_direct_connect_bridge import client as c
    monkeypatch.setattr(c, "read", lambda s, name, host=None: {"SwMerge": 0})
    r = TestClient(create_app()).get("/api/circuits/raw" + G)
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
    from franklinwh_direct_connect_bridge import client as c
    monkeypatch.setattr(c, "writes_enabled", lambda s: True)
    seen = {}

    def fake(s, on, host=None):
        seen["on"] = on
        return {"ok": True, "confirmed": True, "after": {"genEn": 1}}
    monkeypatch.setattr(c, "set_generator_enabled", fake)
    r = TestClient(create_app()).put("/api/generator/enable" + G, json={"enabled": True})
    assert r.status_code == 200 and seen["on"] is True


def test_enable_succeeds_without_hardware_by_design():
    """Unlike set_generator_mode, enabling must NOT refuse when nothing is fitted —
    that is what the official app does, and refusing would block a real install."""
    import inspect
    from franklinwh_direct_connect_bridge import client as c
    assert "NotInstalledError" not in inspect.getsource(c.set_generator_enabled)


# ── #94: no gateway yet is an answer, not a 502 ─────────────────────────────
def test_no_gateway_yet_answers_200_without_device_io(monkeypatch):
    """The UI asks for the generator on page load, before the setup wizard has added a
    gateway. That used to try an empty host and answer 502 (two console errors per load)."""
    from franklinwh_direct_connect_bridge import client as c
    calls = []
    monkeypatch.setattr(c, "generator", lambda *a, **kw: calls.append(1) or {})
    monkeypatch.delenv("FWH_HOST", raising=False)
    monkeypatch.delenv("FWH_HOSTS", raising=False)
    state.register_gateway("gw-nohost", "", "New")      # in the roster, no host yet
    tc = TestClient(create_app())
    try:
        for path in ("/api/generator", "/api/generator/raw"):
            r = tc.get(path + "?gateway=gw-nohost")
            assert r.status_code == 200, (path, r.status_code, r.text)
            assert r.json()["available"] is False and r.json()["reason"]
    finally:
        state.unregister_gateway("gw-nohost")
    assert calls == []
