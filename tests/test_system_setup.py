"""System Setup — derived + override resolution + system.* sensors. Derivation from
the device is mocked (no live aGate in tests); focus on the store/override/snapshot logic."""
from franklinwh_direct_connect_bridge import system_setup as ss
from franklinwh_direct_connect_bridge.db import MetricsStore


def test_defaults_when_nothing_set(tmp_path):
    st = MetricsStore(str(tmp_path / "m.db"))
    v = ss.values(st, settings=None, gateway_id=None, host=None)   # no settings → no derive
    assert v["solar_type"] == "none" and v["solar_kwp"] == 0.0
    assert v["grid_forming"] is True and v["generator_input"] is False
    assert v["battery_label"] == "FranklinWH"
    assert v["_overridden"]["solar_type"] is False


def test_override_wins_and_clears(tmp_path):
    st = MetricsStore(str(tmp_path / "m.db"))
    ss.update(st, None, {"solar_kwp": 6.6, "solar_type": "ac", "whole_home_backup": False,
                         "battery_label": "Home Battery"})
    v = ss.values(st, None, None, None)
    assert v["solar_kwp"] == 6.6 and v["solar_type"] == "ac"
    assert v["whole_home_backup"] is False and v["battery_label"] == "Home Battery"
    assert v["_overridden"]["solar_kwp"] is True
    # clearing (null) reverts to default/derived
    ss.update(st, None, {"solar_kwp": None})
    assert ss.values(st, None, None, None)["solar_kwp"] == 0.0


def test_derive_beats_default_but_override_beats_derive(tmp_path, monkeypatch):
    st = MetricsStore(str(tmp_path / "m.db"))
    monkeypatch.setattr(ss, "_derive", lambda settings, host: {"solar_type": "ac", "solar_kwp": 6.6,
                                                               "generator_input": False})
    v = ss.values(st, settings=object(), gateway_id="g", host="h")
    assert v["solar_kwp"] == 6.6 and v["solar_type"] == "ac"      # derived beats default
    ss.update(st, "g", {"solar_kwp": 10.0})
    assert ss.values(st, object(), "g", "h")["solar_kwp"] == 10.0  # override beats derived


def test_snapshot_keys(tmp_path):
    st = MetricsStore(str(tmp_path / "m.db"))
    snap = ss.snapshot(st, None, None, None)
    assert snap["system.solar_type"] == "none" and snap["system.grid_forming"] is True
    assert set(snap) == {f"system.{k}" for k in
                         ("solar_type", "solar_kwp", "generator_input", "grid_forming",
                          "whole_home_backup", "load_shedding", "non_backup_loads", "battery_label")}


def test_api_get_put_and_sensor_group(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from franklinwh_direct_connect_bridge import app as app_module, config, environment, db
    st = MetricsStore(str(tmp_path / "m.db"))
    monkeypatch.setattr(environment, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "_settings", None)
    monkeypatch.setattr(db, "get_store", lambda s: st)
    monkeypatch.setattr(ss, "_derive", lambda settings, host: {})   # no device
    c = TestClient(app_module.create_app())
    assert c.get("/api/system-setup").json()["values"]["solar_type"] == "none"
    c.put("/api/system-setup", json={"solar_type": "ac", "solar_kwp": 6.6})
    assert c.get("/api/system-setup").json()["values"]["solar_kwp"] == 6.6
    ids = {s["id"]: s["group"] for s in c.get("/api/schedules").json()["sensors"]}
    assert ids.get("system.solar_type") == "System Setup"
