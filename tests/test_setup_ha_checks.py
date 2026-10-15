"""The wizard's last step: four live checks, and one question.

Shape taken from the Modbus Bridge's wizard (owner, 2026-10-15), because the two should
feel like one product. The reason it is FOUR lines rather than one verdict: each fails
independently and the remedy for each is in a different place —

  * our broker connection        → the MQTT tab, or install Mosquitto
  * our link INTO Home Assistant → Home Assistant → Instances
  * HA's own MQTT integration    → HA's Devices & services
  * entities actually present    → nothing, or an orphan purge

"Could not be checked" is a third state. Showing it as a failure sends people to fix
something that may not be broken.
"""
import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import (app as app_module, config, db, environment,
                                              ha_instances, state)
from franklinwh_direct_connect_bridge.db import MetricsStore


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    st = MetricsStore(str(tmp_path / "m.db"))
    monkeypatch.setattr(environment, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "_settings", None)
    monkeypatch.setattr(db, "get_store", lambda s: st)
    monkeypatch.setattr(app_module, "discover_mqtt", lambda: {"found": False})
    state.reset_gateways()
    yield st
    state.reset_gateways()


def _checks(client):
    return {c["id"]: c for c in client.get("/api/setup/ha-checks").json()["checks"]}


def test_all_four_checks_are_reported(ctx):
    c = _checks(TestClient(app_module.create_app()))
    assert set(c) == {"mqtt_broker", "ha_linked", "ha_mqtt", "entities"}
    for check in c.values():
        assert check["title"] and check["detail"]


def test_nothing_configured_reads_as_not_done_with_a_remedy(ctx):
    c = _checks(TestClient(app_module.create_app()))
    assert c["mqtt_broker"]["ok"] is False and c["mqtt_broker"]["remedy"]
    assert c["ha_linked"]["ok"] is False
    assert "Instances" in c["ha_linked"]["remedy"]


def test_unknown_is_not_failure(ctx, monkeypatch):
    """HA's MQTT integration cannot be checked without a link to HA — so it says so."""
    c = _checks(TestClient(app_module.create_app()))
    assert c["ha_mqtt"]["ok"] is None
    assert c["ha_mqtt"]["state"] == "Could not be checked"
    assert c["entities"]["ok"] is None


def test_the_addons_own_home_assistant_is_named_as_such(ctx, monkeypatch):
    ctx.create_ha_instance(ha_id="self", name="Home Assistant (this add-on)",
                           base_url="http://supervisor/core", token="t", is_default=True)
    monkeypatch.setattr(ha_instances, "probe", lambda u, t: {"ok": True, "message": "api running"})
    monkeypatch.setattr(ha_instances, "components", lambda u, t: ["mqtt", "sensor"])
    monkeypatch.setattr(ha_instances, "states", lambda u, t: [])
    c = _checks(TestClient(app_module.create_app()))
    assert c["ha_linked"]["ok"] is True
    assert c["ha_linked"]["state"] == "This Home Assistant"
    assert c["ha_mqtt"]["ok"] is True


def test_leftover_entities_are_counted_and_explained(ctx, monkeypatch):
    """The ones nobody finds on their own: entities from a gateway that no longer exists."""
    ctx.create_ha_instance(ha_id="self", name="HA", base_url="http://supervisor/core",
                           token="t", is_default=True)
    gw = state.register_gateway("g1", "192.0.2.110", "aGate")
    gw.serial = "SNLIVE"
    monkeypatch.setattr(ha_instances, "probe", lambda u, t: {"ok": True})
    monkeypatch.setattr(ha_instances, "components", lambda u, t: ["mqtt"])
    monkeypatch.setattr(ha_instances, "states", lambda u, t: [
        {"entity_id": "sensor.franklinwh_snlive_soc"},
        {"entity_id": "sensor.franklinwh_snlive_grid_w"},
        {"entity_id": "sensor.franklinwh_oldnode_soc"},      # a gateway that is gone
    ])
    c = _checks(TestClient(app_module.create_app()))
    assert c["entities"]["ok"] is True
    assert "2 entities" in c["entities"]["state"]
    assert "1 left over" in c["entities"]["state"]
    assert "MQTT" in c["entities"]["remedy"]


def test_publishing_off_is_stated_as_such_not_as_a_broker_fault(ctx, monkeypatch):
    """"Not publishing" and "broker unreachable" are different problems."""
    monkeypatch.setattr(app_module, "discover_mqtt",
                        lambda: {"found": True, "host": "core-mosquitto", "port": 1883})
    c = _checks(TestClient(app_module.create_app()))
    assert c["mqtt_broker"]["state"] == "Not publishing"
    assert c["mqtt_broker"]["can_enable"] is True       # one click is available
    assert "MQTT tab" in c["mqtt_broker"]["remedy"]


# -- the scan default, with provenance ---------------------------------------------------
def test_the_default_subnet_says_where_it_came_from(ctx):
    d = TestClient(app_module.create_app()).get("/api/gateways/scan/default").json()
    assert d["subnet"] and d["source"] and d["label"]


def test_a_configured_gateway_wins_over_a_guess(ctx):
    ctx.create_gateway(gw_id="g1", label="aGate", host="192.0.2.110")
    d = TestClient(app_module.create_app()).get("/api/gateways/scan/default").json()
    assert d["subnet"] == "192.0.2.0/24" and d["source"] == "gateway"


def test_the_host_network_beats_a_guess_in_the_addon(ctx, monkeypatch):
    from franklinwh_direct_connect_bridge import ha_supervisor
    monkeypatch.setattr(ha_supervisor, "host_lan_subnets", lambda: ["192.168.7.0/24"])
    d = TestClient(app_module.create_app()).get("/api/gateways/scan/default").json()
    assert d["subnet"] == "192.168.7.0/24" and d["source"] == "host"
    assert "host network" in d["label"]


def test_a_guess_is_labelled_as_a_guess(ctx, monkeypatch):
    """The one case where the prefilled value is worth no trust at all."""
    from franklinwh_direct_connect_bridge import ha_supervisor
    from franklinwh_direct_connect_api import discover as _disc
    monkeypatch.setattr(ha_supervisor, "host_lan_subnets", lambda: [])
    monkeypatch.setattr(_disc, "default_gateway", lambda: None)
    d = TestClient(app_module.create_app()).get("/api/gateways/scan/default").json()
    assert d["source"] == "guess" and "check it" in d["label"]
