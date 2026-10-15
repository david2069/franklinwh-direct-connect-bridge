"""As an add-on, configure what the Supervisor already knows — and ask before publishing.

Owner, 2026-10-15, installing the add-on for the first time: "you also need to
self-configure this HA as the local HA instance" and "MQTT did not get setup".

The split is deliberate:
  * registering this Home Assistant is READ-ONLY and happens automatically;
  * turning MQTT publishing on CREATES entities in the user's Home Assistant, so it stays
    an explicit action — the same reasoning that stopped mock gateways publishing.
"""
import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import (app as app_module, config, db, environment,
                                              ha_supervisor)
from franklinwh_direct_connect_bridge.db import MetricsStore


@pytest.fixture
def store(tmp_path, monkeypatch):
    st = MetricsStore(str(tmp_path / "m.db"))
    monkeypatch.setattr(environment, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "_settings", None)
    monkeypatch.setattr(db, "get_store", lambda s: st)
    return st


def _as_addon(monkeypatch, token="supervisor-token-xyz"):
    monkeypatch.setattr(ha_supervisor, "IS_HA_ADDON", True)
    monkeypatch.setenv("SUPERVISOR_TOKEN", token)


# -- the add-on's own Home Assistant -----------------------------------------------------
def test_the_addon_registers_its_own_home_assistant(store, monkeypatch):
    _as_addon(monkeypatch)
    assert app_module._seed_self_ha_instance(config.get_settings()) is True
    rows = store.ha_instances()
    assert len(rows) == 1
    assert rows[0]["base_url"] == ha_supervisor.SUPERVISOR_CORE_API
    assert rows[0]["token"] == "supervisor-token-xyz"
    assert rows[0]["is_default"] == 1


def test_it_is_idempotent(store, monkeypatch):
    _as_addon(monkeypatch)
    app_module._seed_self_ha_instance(config.get_settings())
    assert app_module._seed_self_ha_instance(config.get_settings()) is False
    assert len(store.ha_instances()) == 1


def test_a_users_own_instances_are_never_overwritten(store, monkeypatch):
    _as_addon(monkeypatch)
    store.create_ha_instance(ha_id="mine", name="My HA", base_url="http://192.0.2.5:8123",
                             token="theirs", is_default=True)
    assert app_module._seed_self_ha_instance(config.get_settings()) is False
    assert [r["id"] for r in store.ha_instances()] == ["mine"]


def test_standalone_registers_nothing(store, monkeypatch):
    monkeypatch.setattr(ha_supervisor, "IS_HA_ADDON", False)
    assert app_module._seed_self_ha_instance(config.get_settings()) is False
    assert store.ha_instances() == []


def test_no_supervisor_token_means_no_instance(store, monkeypatch):
    monkeypatch.setattr(ha_supervisor, "IS_HA_ADDON", True)
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    assert ha_supervisor.self_instance() is None


# -- MQTT: offered, not imposed ----------------------------------------------------------
def test_mqtt_availability_is_reported_without_the_password(store, monkeypatch):
    monkeypatch.setattr(app_module, "discover_mqtt",
                        lambda: {"found": True, "host": "core-mosquitto", "port": 1883,
                                 "username": "addons", "password": "s3cret"})
    c = TestClient(app_module.create_app())
    r = c.get("/api/mqtt/supervisor")
    assert r.status_code == 200 and r.json()["available"] is True
    assert r.json()["publishing"] is False
    assert "s3cret" not in r.text


def test_publishing_is_not_turned_on_by_merely_looking(store, monkeypatch):
    """Reading availability must not change anything — entities are the consequence."""
    monkeypatch.setattr(app_module, "discover_mqtt",
                        lambda: {"found": True, "host": "core-mosquitto", "port": 1883,
                                 "username": "addons", "password": "s3cret"})
    saved = []
    monkeypatch.setattr(app_module, "save_override", lambda k, v: saved.append(k))
    TestClient(app_module.create_app()).get("/api/mqtt/supervisor")
    assert saved == []


def test_enabling_adopts_the_broker_explicitly(store, monkeypatch):
    monkeypatch.setattr(app_module, "discover_mqtt",
                        lambda: {"found": True, "host": "core-mosquitto", "port": 1883,
                                 "username": "addons", "password": "s3cret"})
    saved = {}
    monkeypatch.setattr(app_module, "save_override", lambda k, v: saved.__setitem__(k, v))
    r = TestClient(app_module.create_app()).post("/api/mqtt/supervisor/enable")
    assert r.status_code == 200 and r.json()["ok"] is True
    assert saved["mqtt_enabled"] is True
    assert saved["mqtt_host"] == "core-mosquitto" and saved["mqtt_port"] == 1883
    assert saved["mqtt_username"] == "addons" and saved["mqtt_password"] == "s3cret"


def test_enabling_without_a_broker_is_a_clear_refusal(store, monkeypatch):
    monkeypatch.setattr(app_module, "discover_mqtt",
                        lambda: {"found": False, "error": "No MQTT service registered"})
    r = TestClient(app_module.create_app()).post("/api/mqtt/supervisor/enable")
    assert r.status_code == 409
    assert "MQTT service" in r.json()["detail"]
