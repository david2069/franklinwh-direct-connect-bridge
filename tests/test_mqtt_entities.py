"""MQTT entities — richer catalogue + opt-in groups + multi-gateway-complete endpoint."""
from franklinwh_direct_connect_bridge.publish import entities
from franklinwh_direct_connect_bridge.db import MetricsStore


def test_entities_grouped_and_controls_included():
    keys = {e["key"] for e in entities.ENTITIES}
    assert {"soc", "run_status", "battery_status"} <= keys      # new entities present
    assert all("group" in e for e in entities.ENTITIES)
    assert {c["key"] for c in entities.CONTROLS} >= {"operating_mode", "smart_circuit_1"}


def test_discovery_configs_filter_by_group():
    all_cfgs, _, _ = entities.discovery_configs("n", {}, "p", "d")   # default groups
    core_cfgs, _, _ = entities.discovery_configs("n", {}, "p", "d", ["core"])
    assert len(core_cfgs) == 2 and len(all_cfgs) > len(core_cfgs)    # core = soc + mode
    # controls only appear when the controls group is enabled
    no_ctrl, _, _ = entities.discovery_configs("n", {}, "p", "d", ["power"])
    assert not any("/switch/" in t or "/select/" in t for t, _ in no_ctrl)


def test_enabled_from_store(tmp_path):
    st = MetricsStore(str(tmp_path / "m.db"))
    assert set(entities.enabled_from_store(st)) == set(entities.default_groups())
    st.set_config("mqtt_groups", '["core","power"]')
    assert set(entities.enabled_from_store(st)) == {"core", "power"}
    st.set_config("mqtt_groups", '["core","bogus"]')                # unknown dropped
    assert entities.enabled_from_store(st) == ["core"]


def test_build_state_adds_run_and_battery_status():
    st = entities.build_state({"p_fhp": -1500, "run_status": 2}, {})
    assert st["battery_status"] == "charging" and st["run_status"] == 2
    assert entities.build_state({"p_fhp": 800}, {})["battery_status"] == "discharging"


def test_api_entities_and_groups(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from franklinwh_direct_connect_bridge import app as app_module, config, environment, db
    st = MetricsStore(str(tmp_path / "m.db"))
    monkeypatch.setattr(environment, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "_settings", None)
    monkeypatch.setattr(db, "get_store", lambda s: st)
    c = TestClient(app_module.create_app())
    e = c.get("/api/mqtt/entities").json()
    assert "entities" in e and "publishing" in e and "groups" in e
    assert any(x["writable"] for x in e["entities"])               # controls included
    n_all = len(e["entities"])
    assert c.put("/api/mqtt/groups", json={"groups": ["core", "power", "energy", "controls"]}).status_code == 200
    e2 = c.get("/api/mqtt/entities").json()
    assert len(e2["entities"]) < n_all and not any(x["diagnostic"] for x in e2["entities"])


def test_poller_mqtt_path_uses_defined_names():
    """Regression (BUG-MQTT-PUBENTITIES): the poller's MQTT-start path referenced an
    undefined `_pub_entities`, so every publish crashed with NameError and HA discovery
    never went out. Guard that the module binds every name it loads to an import/def."""
    import ast
    from franklinwh_direct_connect_bridge import poller

    src = ast.parse(open(poller.__file__).read())
    imported = {a.asname or a.name for n in ast.walk(src)
                if isinstance(n, ast.ImportFrom) for a in n.names}
    imported |= {a.asname or a.name.split(".")[0] for n in ast.walk(src)
                 if isinstance(n, ast.Import) for a in n.names}
    # the symbol the MQTT-start path uses must resolve at module scope
    assert "entities" in imported
    assert not any(isinstance(n, ast.Name) and n.id == "_pub_entities"
                   for n in ast.walk(src)), "stray undefined `_pub_entities` is back"
    # and the resolver it calls actually exists + is callable
    assert callable(entities.enabled_from_store)
