"""Automation constants (const.* sensors) — KV store, clamp/persist, snapshot."""
from franklinwh_direct_connect_bridge.db import MetricsStore
from franklinwh_direct_connect_bridge import constants as C
from franklinwh_direct_connect_bridge import scheduler


def test_app_config_kv_round_trip(tmp_path):
    st = MetricsStore(str(tmp_path / "m.db"))
    assert st.get_config("missing") is None
    assert st.get_config("missing", "dflt") == "dflt"
    st.set_config("k", '{"a":1}')
    assert st.get_config("k") == '{"a":1}'
    st.set_config("k", '{"a":2}')          # upsert
    assert st.get_config("k") == '{"a":2}'


def test_constants_defaults_and_update_clamp(tmp_path):
    st = MetricsStore(str(tmp_path / "m.db"))
    v = C.values(st)
    assert v["min_discharge_soc"] == 20.0 and v["max_charge_soc"] == 100.0 and v["demand_charge_min_soc"] == 30.0
    # clamp out-of-range + persist; unknown keys ignored
    out = C.update(st, {"min_discharge_soc": 250, "max_charge_soc": -5, "bogus": 9})
    assert out["min_discharge_soc"] == 100.0 and out["max_charge_soc"] == 0.0
    assert "bogus" not in out
    # persisted across a fresh store on the same file
    st2 = MetricsStore(str(tmp_path / "m.db"))
    assert C.values(st2)["min_discharge_soc"] == 100.0
    # partial update keeps the other value
    C.update(st2, {"demand_charge_min_soc": 42})
    v2 = C.values(st2)
    assert (v2["min_discharge_soc"], v2["max_charge_soc"], v2["demand_charge_min_soc"]) == (100.0, 0.0, 42.0)


def test_constants_snapshot_keys(tmp_path):
    st = MetricsStore(str(tmp_path / "m.db"))
    C.update(st, {"min_discharge_soc": 25})
    snap = scheduler.const_snapshot(st)
    assert snap["const.min_discharge_soc"] == 25.0
    assert {"const.min_discharge_soc", "const.max_charge_soc", "const.demand_charge_min_soc",
            "const.battery_capacity_kwh", "const.battery_max_power_kw",
            "const.default_operating_mode"} == set(snap)


def test_constants_snapshot_no_store():
    assert C.values(None)["max_charge_soc"] == 100.0
    assert scheduler.const_snapshot(None)["const.max_charge_soc"] == 100.0


def test_spec_shape():
    sp = C.spec()
    assert sp["min_discharge_soc"] == {"default": 20.0, "min": 0.0, "max": 100.0}


# ── API: GET/PUT + clamp + sensor group + const.* in evaluate ──
def _client(tmp_path, monkeypatch, store):
    from fastapi.testclient import TestClient
    from franklinwh_direct_connect_bridge import app as app_module, config, environment, db
    monkeypatch.setattr(environment, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "_settings", None)
    monkeypatch.setattr(db, "get_store", lambda s: store)
    config.save_override("allow_writes", True)
    return TestClient(app_module.create_app())


def test_api_constants_get_put_and_sensor_group(tmp_path, monkeypatch):
    st = MetricsStore(str(tmp_path / "m.db"))
    c = _client(tmp_path, monkeypatch, st)

    g = c.get("/api/constants").json()
    assert g["values"]["max_charge_soc"] == 100.0 and g["spec"]["min_discharge_soc"]["max"] == 100.0

    # in-range values persist; the model itself rejects out-of-[0,100] (see below)
    r = c.put("/api/constants", json={"min_discharge_soc": 15, "demand_charge_min_soc": 35})
    assert r.status_code == 200
    v = r.json()["values"]
    assert v["min_discharge_soc"] == 15.0 and v["demand_charge_min_soc"] == 35.0
    # persisted (fresh GET reflects it)
    assert c.get("/api/constants").json()["values"]["min_discharge_soc"] == 15.0
    # out-of-range is a 422 at the model boundary (parity with Modbus ge/le bounds)
    assert c.put("/api/constants", json={"max_charge_soc": 250}).status_code == 422

    # surfaced as a picker group + as a live sensor value in evaluate
    sensors = c.get("/api/schedules").json()["sensors"]
    ids = {s["id"]: s["group"] for s in sensors}
    assert ids.get("const.min_discharge_soc") == "Automation Constants"

    ev = c.post("/api/schedules/evaluate", json={"match": "ALL", "conditions": [
        {"sensor": "const.demand_charge_min_soc", "op": ">=", "value": 30}]})
    assert ev.status_code == 200 and ev.json()["result"] is True


def test_api_constants_rejects_non_numeric(tmp_path, monkeypatch):
    st = MetricsStore(str(tmp_path / "m.db"))
    c = _client(tmp_path, monkeypatch, st)
    r = c.put("/api/constants", json={"min_discharge_soc": "abc"})
    assert r.status_code == 422


# ── default_operating_mode constant ──
def test_default_operating_mode_store_and_snapshot(tmp_path):
    st = MetricsStore(str(tmp_path / "m.db"))
    assert C.values(st)["default_operating_mode"] == "self"          # default
    out = C.update(st, {"default_operating_mode": "tou"})
    assert out["default_operating_mode"] == "tou"
    # unknown mode is ignored (kept previous)
    assert C.update(st, {"default_operating_mode": "bogus"})["default_operating_mode"] == "tou"
    snap = scheduler.const_snapshot(st)
    assert snap["const.default_operating_mode"] == "tou"
    # spec carries the option catalogue
    opts = {o["value"] for o in C.spec()["default_operating_mode"]["options"]}
    assert opts == {"self", "tou", "backup"}


def test_api_constants_accepts_mode_and_rejects_bad(tmp_path, monkeypatch):
    st = MetricsStore(str(tmp_path / "m.db"))
    c = _client(tmp_path, monkeypatch, st)
    assert c.put("/api/constants", json={"default_operating_mode": "backup"}).status_code == 200
    assert c.get("/api/constants").json()["values"]["default_operating_mode"] == "backup"
    assert c.put("/api/constants", json={"default_operating_mode": "nope"}).status_code == 422
    # the const.* sensor group includes the mode
    ids = {s["id"] for s in c.get("/api/schedules").json()["sensors"]}
    assert "const.default_operating_mode" in ids
