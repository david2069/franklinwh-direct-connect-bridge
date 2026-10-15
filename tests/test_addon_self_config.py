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


# -- the PV array size comes from the gateway ---------------------------------------------
# Owner, 2026-10-15: "Solar PV size to sync from gateway local api". The aGate reports the
# array (1903 solar_pv); typing it from memory is how a forecast ends up scaled wrong.

def test_derived_pv_kwp_is_reported_when_the_gateway_says_so(store, monkeypatch):
    from franklinwh_direct_connect_bridge import system_setup
    monkeypatch.setattr(system_setup, "values",
                        lambda *a, **k: {"solar_kwp": 6.6, "_derived": {"solar_kwp": 6.6}})
    c = TestClient(app_module.create_app())
    assert c.get("/api/settings").json()["location"]["derived_pv_kwp"] == 6.6


def test_a_default_is_not_a_measurement(store, monkeypatch):
    """solar_kwp that came from the DEFAULT, not the device, must not be offered as the
    gateway's answer — that is how a made-up number acquires authority."""
    from franklinwh_direct_connect_bridge import system_setup
    monkeypatch.setattr(system_setup, "values",
                        lambda *a, **k: {"solar_kwp": 5.0, "_derived": {}})
    c = TestClient(app_module.create_app())
    assert c.get("/api/settings").json()["location"]["derived_pv_kwp"] is None


def test_an_unreadable_gateway_reports_none_not_zero(store, monkeypatch):
    """"Could not ask" and "no solar" are different facts."""
    from franklinwh_direct_connect_bridge import system_setup

    def _boom(*a, **k):
        raise OSError("gateway unreachable")
    monkeypatch.setattr(system_setup, "values", _boom)
    c = TestClient(app_module.create_app())
    assert c.get("/api/settings").json()["location"]["derived_pv_kwp"] is None


def test_the_ui_offers_it_rather_than_overwriting():
    from pathlib import Path
    html = (Path(__file__).resolve().parents[1]
            / "src/franklinwh_direct_connect_bridge/templates/tabs/settings.html").read_text()
    block = html[html.index("PV size (kWp)"):html.index("Wholesale region")]
    assert "derivedPvKwp" in block and "use it" in block
    # shown only when it DIFFERS — no nagging when the two already agree
    assert "Number(form.pv_kwp) !== derivedPvKwp" in block


# -- publishing works out of the box in the add-on ----------------------------------------
# Owner, 2026-10-15, comparing this with the two sibling bridges: "Modbus Bridge and FWHAI
# are working - why have u still not fixed your MQTT interface!" Both configure the broker
# from the Supervisor and publish; ours shipped with publishing off and only filled the
# broker in once it was on, so turning it on found nothing configured.

def test_the_addon_defaults_to_publishing():
    """A new add-on install publishes; existing installs keep whatever they have."""
    from pathlib import Path
    cfg = (Path(__file__).resolve().parents[1] / "config.yaml").read_text()
    opts = cfg[cfg.index("options:"):cfg.index("schema:")]
    assert "mqtt_enabled: true" in opts


def test_broker_credentials_are_filled_even_while_publishing_is_off(monkeypatch):
    """So the switch works the moment it is flipped, instead of finding nothing set."""
    from franklinwh_direct_connect_bridge.config import Settings
    monkeypatch.setattr(ha_supervisor, "IS_HA_ADDON", True)
    monkeypatch.setattr(ha_supervisor, "discover_mqtt",
                        lambda: {"found": True, "host": "core-mosquitto", "port": 1883,
                                 "username": "addons", "password": "p"})
    s = Settings(mqtt_enabled=False, mqtt_host="", mqtt_username="")
    assert ha_supervisor.apply_supervisor_mqtt(s) is True
    assert s.mqtt_host == "core-mosquitto" and s.mqtt_username == "addons"
    assert s.mqtt_enabled is False          # filling creds does NOT start publishing


def test_user_supplied_credentials_are_still_left_alone(monkeypatch):
    from franklinwh_direct_connect_bridge.config import Settings
    monkeypatch.setattr(ha_supervisor, "IS_HA_ADDON", True)
    monkeypatch.setattr(ha_supervisor, "discover_mqtt",
                        lambda: {"found": True, "host": "core-mosquitto", "port": 1883,
                                 "username": "addons", "password": "p"})
    s = Settings(mqtt_enabled=True, mqtt_host="192.0.2.50", mqtt_username="me")
    assert ha_supervisor.apply_supervisor_mqtt(s) is False
    assert s.mqtt_host == "192.0.2.50"


def test_enabling_takes_effect_without_a_restart(store, monkeypatch):
    """The poller holds the live settings object and re-checks it on its retry tick, so
    mutating that object is what makes 'takes effect now' true."""
    from franklinwh_direct_connect_bridge import config
    monkeypatch.setattr(app_module, "discover_mqtt",
                        lambda: {"found": True, "host": "core-mosquitto", "port": 1883,
                                 "username": "addons", "password": "p"})
    monkeypatch.setattr(app_module, "save_override", lambda k, v: None)
    live = config.get_settings()
    live.mqtt_enabled = False
    r = TestClient(app_module.create_app()).post("/api/mqtt/supervisor/enable")
    assert r.status_code == 200 and r.json()["restart_required"] is False
    # the SAME object the pollers hold
    assert config.get_settings() is live
    assert live.mqtt_enabled is True and live.mqtt_host == "core-mosquitto"
