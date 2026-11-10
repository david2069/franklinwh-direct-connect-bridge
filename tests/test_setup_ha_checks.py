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
    monkeypatch.setattr(ha_instances, "bridge_entities", lambda u, t: [
        ("sensor.franklinwh_direct_snlive_soc", ["franklinwh_snlive"]),
        ("sensor.franklinwh_direct_snlive_grid_w", ["franklinwh_snlive"]),
        ("sensor.franklinwh_direct_oldnode_soc", ["franklinwh_oldnode"]),   # a gateway that is gone
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


# -- #84: the broker check asks the publishers, not the default gateway ----------------------

def _mqtt_on(monkeypatch):
    s = config.get_settings()
    monkeypatch.setattr(s, "mqtt_enabled", True)


def test_no_publishing_gateway_is_not_a_broker_failure(ctx, monkeypatch):
    """Fresh install: nothing has tried to connect yet. That is not "Not connected"."""
    _mqtt_on(monkeypatch)
    c = _checks(TestClient(app_module.create_app()))
    assert c["mqtt_broker"]["ok"] is None
    assert c["mqtt_broker"]["state"] == "No gateway publishing yet"
    assert "add a gateway" in c["mqtt_broker"]["remedy"]


def test_a_stopped_default_does_not_hide_a_connected_publisher(ctx, monkeypatch):
    _mqtt_on(monkeypatch)
    dead = state.register_gateway("g1", "192.0.2.10", "first", publish_ha=True)
    dead.mqtt_connected = False                     # e.g. its poller has stopped
    live = state.register_gateway("g2", "192.0.2.11", "second", publish_ha=True)
    live.mqtt_connected = True
    c = _checks(TestClient(app_module.create_app()))
    assert c["mqtt_broker"]["ok"] is True and c["mqtt_broker"]["state"] == "Connected"


def test_publishers_that_cannot_connect_still_fail(ctx, monkeypatch):
    _mqtt_on(monkeypatch)
    gw = state.register_gateway("g1", "192.0.2.10", "only", publish_ha=True)
    gw.mqtt_connected = False
    c = _checks(TestClient(app_module.create_app()))
    assert c["mqtt_broker"]["ok"] is False and c["mqtt_broker"]["state"] == "Not connected"


def test_a_gateway_that_does_not_publish_is_not_asked(ctx, monkeypatch):
    _mqtt_on(monkeypatch)
    state.register_gateway("m1", "127.0.0.1", "mock", is_mock=True, publish_ha=False)
    c = _checks(TestClient(app_module.create_app()))
    assert c["mqtt_broker"]["state"] == "No gateway publishing yet"


# -- #83: entities are ours by DEVICE identity, not by entity_id text ------------------------

def _linked(ctx, monkeypatch):
    ctx.create_ha_instance(ha_id="self", name="HA", base_url="http://supervisor/core",
                           token="t", is_default=True)
    monkeypatch.setattr(ha_instances, "probe", lambda u, t: {"ok": True})
    monkeypatch.setattr(ha_instances, "components", lambda u, t: ["mqtt"])


def test_entities_named_after_the_last_8_of_the_serial_are_ours(ctx, monkeypatch):
    """0.4.0 names devices after the serial's last 8 characters, so entity_ids no longer
    contain the full serial. They were all counted as "left over" (#83)."""
    _linked(ctx, monkeypatch)
    gw = state.register_gateway("g1", "192.0.2.110", "aGate")
    gw.serial = "10060006A0000000AB12CD34"
    full = "franklinwh_10060006a0000000ab12cd34"
    monkeypatch.setattr(ha_instances, "bridge_entities", lambda u, t: [
        ("sensor.franklinwh_direct_ab12cd34_state_of_charge", [full]),
        ("sensor.franklinwh_direct_ab12cd34_grid_power", [full]),
        ("sensor.franklinwh_agate_local_bridge_soc", [full]),   # pre-0.4.0 id, same device
    ])
    c = _checks(TestClient(app_module.create_app()))
    assert c["entities"]["ok"] is True
    assert c["entities"]["state"] == "3 entities"
    assert c["entities"]["remedy"] == ""


def test_registry_unreadable_is_could_not_be_checked(ctx, monkeypatch):
    _linked(ctx, monkeypatch)
    state.register_gateway("g1", "192.0.2.110", "aGate").serial = "SN1"
    def boom(u, t):
        raise OSError("template endpoint unavailable")
    monkeypatch.setattr(ha_instances, "bridge_entities", boom)
    c = _checks(TestClient(app_module.create_app()))
    assert c["entities"]["ok"] is None and c["entities"]["state"] == "Could not be checked"


def test_bridge_entities_parses_the_template_answer(monkeypatch):
    import io, json as _json
    body = _json.dumps([["sensor.x", [["mqtt", "franklinwh_sn1"]]],
                        ["switch.y", [["mqtt", "franklinwh_sn1"], ["bad"]]]]).encode()
    seen = {}
    def fake_urlopen(req, timeout=0):
        seen["url"], seen["method"] = req.full_url, req.get_method()
        seen["template"] = _json.loads(req.data)["template"]
        class R(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *a): return False
        return R(body)
    monkeypatch.setattr(ha_instances.urllib.request, "urlopen", fake_urlopen)
    rows = ha_instances.bridge_entities("http://supervisor/core", "t")
    assert seen["url"].endswith("/api/template") and seen["method"] == "POST"
    assert "Direct Connect Bridge" in seen["template"]       # owned by sw_version
    assert rows == [("sensor.x", ["franklinwh_sn1"]), ("switch.y", ["franklinwh_sn1"])]


def test_a_gateway_that_is_actually_publishing_counts_whatever_its_flag_says(ctx, monkeypatch):
    """Seen on HAOS (0.4.1): a wizard-created mock read publish_ha=False while its publisher
    was connected and its device was in HA. The check must follow what is happening."""
    _mqtt_on(monkeypatch)
    gw = state.register_gateway("m1", "127.0.0.1", "mock", is_mock=True, publish_ha=False)
    gw.mqtt_connected = True
    c = _checks(TestClient(app_module.create_app()))
    assert c["mqtt_broker"]["ok"] is True and c["mqtt_broker"]["state"] == "Connected"
