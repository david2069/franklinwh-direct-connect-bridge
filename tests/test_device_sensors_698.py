"""#698 phase 1: Smart Circuits, generator and V2L as scheduler sensors, from what each
poll already reads (no extra aGate traffic). Owner 2026-11-17: typing "Circ" in the
sensor picker found nothing."""
import datetime as dt
import pathlib
from types import SimpleNamespace

from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import app as app_module
from franklinwh_direct_connect_bridge import db, state
from franklinwh_direct_connect_bridge import scheduler as sch

ROOT = pathlib.Path(__file__).resolve().parents[1] / "src/franklinwh_direct_connect_bridge"

SUMMARY = {"ok": True,
           "circuits_on": {1: True, 2: False, 3: False},
           "circuit_names": {1: "Pool pump", 2: "Spa", 3: ""},
           "carsw_enabled": True}


def test_circuit_state_and_names_come_from_the_poll():
    snap = sch.device_snapshot(SUMMARY)
    assert snap["circuit.1.on"] == 1 and snap["circuit.2.on"] == 0
    assert snap["circuit.1.name"] == "Pool pump" and snap["circuit.3.name"] is None
    assert snap["v2l.enabled"] == 1
    # keys that went through JSON are strings
    js = {"circuits_on": {"1": True}, "circuit_names": {"1": "Pool pump"}}
    assert sch.device_snapshot(js)["circuit.1.on"] == 1


def test_nothing_read_is_no_reading_never_zero():
    snap = sch.device_snapshot({})
    for n in (1, 2, 3):
        assert snap[f"circuit.{n}.on"] is None and snap[f"circuit.{n}.name"] is None
    assert snap["v2l.enabled"] is None
    assert sch.snapshot_from_state({})["generator.today_kwh"] is None


def test_generator_energy_today_from_the_poll():
    assert sch.snapshot_from_state({"kwh_gen": 1.25})["generator.today_kwh"] == 1.25


def test_on_off_works_as_a_condition():
    snap = sch.device_snapshot(SUMMARY)
    assert sch.evaluate([{"sensor": "circuit.1.on", "op": "==", "value": 1}], snap)
    assert not sch.evaluate([{"sensor": "circuit.2.on", "op": "==", "value": 1}], snap)
    # no reading: false for every operator
    assert not sch.evaluate([{"sensor": "circuit.1.on", "op": "==", "value": 0}],
                            sch.device_snapshot({}))


def test_the_new_sensors_are_in_the_catalogue_with_a_feature():
    ids = sch.known_sensor_ids()
    for sid in ("circuit.1.on", "circuit.2.on", "circuit.3.on", "circuit.1.name",
                "generator.today_kwh", "generator.installed", "v2l.installed", "v2l.enabled"):
        assert sid in ids, sid
        assert sch.sensor_feature(sid) == "gateway"


def test_picker_labels_find_circ_and_use_the_agate_names():
    rows = sch.device_sensor_rows({1: ["Pool pump"], 2: ["Spa", "Heater"]})
    by = {r["id"]: r for r in rows}
    assert by["circuit.1.on"]["label"] == "Smart circuit 1 (Pool pump): on"
    assert by["circuit.2.on"]["label"] == "Smart circuit 2 (Spa / Heater): on"
    assert by["circuit.3.on"]["label"] == "Smart circuit 3: on"
    assert by["circuit.1.on"]["group"] == "Smart Circuits"
    assert by["generator.today_kwh"]["group"] == "Generator"
    assert by["v2l.installed"]["group"] == "V2L"
    for word in ("circ", "gen", "v2l"):
        assert any(word in (r["label"] + r["id"]).lower() for r in rows), word


def test_build_snapshot_has_them_for_the_gateway(tmp_path, monkeypatch):
    state.reset_gateways()
    try:
        g = state.register_gateway("g1", "192.0.2.10", "g1")
        g.last_summary = dict(SUMMARY)
        store = db.MetricsStore(str(tmp_path / "m.db"))
        snap = sch.build_snapshot(None, store, {"kwh_gen": 0.5}, host=None,
                                  gateway_id="g1",
                                  now=dt.datetime(2026, 11, 17, 12, tzinfo=dt.timezone.utc))
        assert snap["circuit.1.on"] == 1 and snap["circuit.1.name"] == "Pool pump"
        assert snap["generator.today_kwh"] == 0.5
        assert snap["generator.installed"] in (0, 1) and snap["v2l.installed"] in (0, 1)
    finally:
        state.reset_gateways()


def test_the_api_offers_them(tmp_path, monkeypatch):
    state.reset_gateways()
    try:
        store = db.MetricsStore(str(tmp_path / "m.db"))
        monkeypatch.setattr(db, "get_store", lambda *a, **k: store)
        g = state.register_gateway("g1", "192.0.2.10", "g1")
        g.last_summary = dict(SUMMARY)
        c = TestClient(app_module.create_app())
        sensors = c.get("/api/schedules").json()["sensors"]
        labels = {s["id"]: s["label"] for s in sensors}
        assert labels["circuit.1.on"] == "Smart circuit 1 (Pool pump): on"
        assert "generator.installed" in labels and "v2l.enabled" in labels
    finally:
        state.reset_gateways()


# ── owner 2026-11-17: an accessory that isn't installed is greyed out in the picker ──
def test_not_installed_accessories_are_greyed_with_a_reason():
    acc = {"circuits": 2, "generator": False, "v2l": True}
    assert sch.device_inactive("circuit.3.on", acc) == "not installed"
    assert sch.device_inactive("circuit.3.name", acc) == "not installed"
    assert sch.device_inactive("circuit.2.on", acc) is None
    assert sch.device_inactive("generator.today_kwh", acc) == "not installed"
    assert sch.device_inactive("v2l.enabled", acc) is None
    # the installed flags themselves stay pickable, and other sensors are untouched
    assert sch.device_inactive("generator.installed", acc) is None
    assert sch.device_inactive("battery.soc_pct", acc) is None
    # not known is never greyed (nothing hidden on a guess)
    unknown = {"circuits": None, "generator": None, "v2l": None}
    for sid in ("circuit.3.on", "generator.today_kwh", "v2l.enabled"):
        assert sch.device_inactive(sid, unknown) is None
    assert sch.device_inactive("v2l.enabled", {"v2l": False}) == "not installed"


def test_installed_comes_from_setup_the_circuit_setting_and_the_model(tmp_path, monkeypatch):
    from franklinwh_direct_connect_bridge import system_setup
    store = db.MetricsStore(str(tmp_path / "m.db"))
    monkeypatch.setattr(system_setup, "_derive_cache",
                        {"192.0.2.10": (float("inf"), {"generator_input": False, "v2l": True})})
    g = SimpleNamespace(id="g1", active_host="192.0.2.10", configured_host="192.0.2.10",
                        last_summary={"circuits_expected": 2})
    acc = sch.accessories(store, SimpleNamespace(smart_circuit_count="auto"), g)
    assert acc == {"circuits": 2, "generator": False, "v2l": True}
    # the Smart Circuits count setting wins over the model
    assert sch.accessories(store, SimpleNamespace(smart_circuit_count="3"), g)["circuits"] == 3
    # the user's System Setup choice wins over what was read
    store.set_config("system_setup:g1", '{"generator_input": true}')
    assert sch.accessories(store, SimpleNamespace(smart_circuit_count="auto"), g)["generator"] is True


def test_the_api_greys_them_per_gateway_and_keeps_them_listed(tmp_path, monkeypatch):
    from franklinwh_direct_connect_bridge import system_setup
    state.reset_gateways()
    try:
        store = db.MetricsStore(str(tmp_path / "m.db"))
        monkeypatch.setattr(db, "get_store", lambda *a, **k: store)
        monkeypatch.setattr(system_setup, "_derive_cache", {
            "192.0.2.10": (float("inf"), {"generator_input": False, "v2l": False}),
            "192.0.2.20": (float("inf"), {"generator_input": True, "v2l": False})})
        a = state.register_gateway("a", "192.0.2.10", "a")
        a.last_summary = {**SUMMARY, "circuits_expected": 2}
        b = state.register_gateway("b", "192.0.2.20", "b")
        b.last_summary = {**SUMMARY, "circuits_expected": 3}
        c = TestClient(app_module.create_app())
        rows = {s["id"]: s for s in c.get("/api/schedules").json()["sensors"]}
        # still listed
        assert "circuit.3.on" in rows and "generator.today_kwh" in rows
        # V2L on neither: greyed for every gateway
        assert rows["v2l.enabled"]["inactive"] == "not installed"
        # generator on b only: greyed for a, pickable for b and for All gateways
        assert rows["generator.today_kwh"]["inactive"] is None
        assert rows["generator.today_kwh"]["inactive_gw"] == {"a": "not installed"}
        assert rows["circuit.3.on"]["inactive_gw"] == {"a": "not installed"}
    finally:
        state.reset_gateways()


def test_the_picker_greys_by_the_schedules_gateway():
    js = (ROOT / "static/js/scheduler_tab.js").read_text()
    assert "inactive_gw" in js and "sensorInactive(" in js
