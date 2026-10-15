"""One Home Assistant device per INTEGRATION per aGate.

Owner's decision, 2026-10-15, relayed by the Modbus Bridge session: "There are DIFFERENT
DEVICES BECAUSE THEY ARE DIFFERENT INTEGRATIONS!! FranklinWH Modbus, FranklinWH Direct,
FranklinWH Cloud with SUFFIX on the Short Serial."

It exists because two sibling integrations both published device id
``franklinwh_<SERIAL>``: Home Assistant merged them into ONE device of 155 entities, their
discovery configs overwrote each other, and an operating-mode command ran on both.

The split is deliberate:
  * the DEVICE identifier gains the integration word immediately — HA re-keys the device
    and entities keep their unique_ids, so history survives;
  * the ENTITY ids change only when the namespace is changed, which is an explicit,
    confirm-gated action, because it creates new entities.
"""
import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import app as app_module, config, db, environment
from franklinwh_direct_connect_bridge.config import Settings
from franklinwh_direct_connect_bridge.db import MetricsStore
from franklinwh_direct_connect_bridge.publish import entities
from franklinwh_direct_connect_bridge.publish.mqtt_publisher import topic_root

SERIAL = "10060006A02F24170091"      # pii: allow — documentation placeholder


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(environment, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "_settings", None)
    monkeypatch.setattr(db, "get_store", lambda s: MetricsStore(str(tmp_path / "m.db")))
    monkeypatch.setattr(app_module, "save_override", lambda k, v: None)
    return TestClient(app_module.create_app())


# -- the device identifier, which is the free half ---------------------------------------
def test_the_identifier_names_the_integration():
    assert entities.device_identifier(SERIAL) == f"franklinwh_direct_{SERIAL}"
    assert entities.device_identifier(SERIAL, "fwh_dc") == f"fwh_dc_direct_{SERIAL}"


def test_two_integrations_on_one_agate_cannot_collide():
    """The exact failure this rule exists to prevent: same serial, same broker."""
    ours = entities.device_identifier(SERIAL)
    theirs = f"franklinwh_modbus_{SERIAL}"
    assert ours != theirs
    assert ours != f"franklinwh_{SERIAL}"      # and not the merged legacy id either


def test_the_entity_ids_do_not_move_with_the_device_identifier():
    """The cheap half must stay cheap: entity unique_ids keep the legacy namespace, so
    Home Assistant renames the device and the history stays attached."""
    cfgs, _, _ = entities.discovery_configs(
        "n1", entities.device_info("n1", SERIAL), "franklinwh-local", "homeassistant")
    uids = [__import__("json").loads(p)["unique_id"] if isinstance(p, str) else p["unique_id"]
            for _t, p in cfgs]
    assert all(u.startswith("franklinwh_n1_") for u in uids)


# -- the namespace, which is the expensive half ------------------------------------------
def test_a_new_namespace_changes_entity_ids_and_the_topic_root():
    cfgs, state_topic, _ = entities.discovery_configs(
        "n1", entities.device_info("n1", SERIAL, namespace="fwh_dc"),
        "fwh-dc", "homeassistant", namespace="fwh_dc")
    payload = cfgs[0][1]
    uid = (__import__("json").loads(payload) if isinstance(payload, str) else payload)["unique_id"]
    assert uid.startswith("fwh_dc_n1_")
    assert state_topic == "fwh-dc/n1/state"


def test_the_topic_root_follows_the_namespace():
    assert topic_root(Settings(mqtt_namespace="franklinwh")) == "franklinwh-local"
    assert topic_root(Settings(mqtt_namespace="fwh_dc")) == "fwh-dc"


def test_changing_the_namespace_needs_confirmation(client):
    r = client.post("/api/mqtt/namespace", json={"namespace": "fwh_dc"})
    assert r.status_code == 428
    assert "confirm" in r.json()["detail"]


def test_a_malformed_namespace_is_refused(client):
    for bad in ("FWH DC", "x", "fwh-dc!", ""):
        r = client.post("/api/mqtt/namespace",
                        json={"namespace": bad, "confirm": True})
        assert r.status_code == 422, bad


def test_the_cost_is_stated_before_the_change(client):
    body = client.get("/api/mqtt/namespace").json()
    assert body["namespace"] == "franklinwh" and body["recommended"] == "fwh_dc"
    assert "history" in body["cost"].lower()
    assert body["device_identifier_example"].startswith("franklinwh_direct_")


def test_changing_it_clears_the_old_entities_and_restarts_publishing(client, monkeypatch):
    """Leaving the old discovery configs retained would leave a second, dead device in
    Home Assistant for ever — the broker re-serves them on every restart."""
    from franklinwh_direct_connect_bridge import state
    state.reset_gateways()
    gw = state.register_gateway("g1", "192.0.2.110", "aGate")
    r = client.post("/api/mqtt/namespace", json={"namespace": "fwh_dc", "confirm": True})
    assert r.status_code == 200 and r.json()["changed"] is True
    assert gw.unpublish_requested is True            # old identity cleared
    assert gw.publisher_restart_requested is True    # new identity published
    state.reset_gateways()


def test_commands_are_subscribed_on_the_same_root_they_are_advertised_on(monkeypatch):
    """A command topic the publisher never subscribes to loses commands in silence —
    the worst failure this surface can have. Found during the cross-bridge audit."""
    from franklinwh_direct_connect_bridge.publish import mqtt_publisher as mp

    captured = {}

    class _FakeClient:
        def __init__(self, *a, **k): pass
        def username_pw_set(self, *a): pass
        def will_set(self, *a, **k): pass
        def connect(self, *a, **k): pass
        def loop_start(self): pass
        def subscribe(self, f): captured["filter"] = f
        def publish(self, *a, **k): pass
        def is_connected(self): return True

    monkeypatch.setattr(mp.mqtt, "Client", _FakeClient)
    s = Settings(mqtt_namespace="fwh_dc", mqtt_prefix="franklinwh-local")
    pub = mp.MqttPublisher(s, "n1", entities.device_info("n1", SERIAL, namespace="fwh_dc"))
    assert pub.state_topic.startswith("fwh-dc/")
    assert pub.cmd_filter.startswith("fwh-dc/")      # NOT the legacy mqtt_prefix


def test_the_discovery_topic_is_keyed_on_the_node_so_a_rename_replaces_in_place():
    """Why the identifier change does not strand a device: the retained CONFIG topic is
    per node, so the new payload overwrites the old one and Home Assistant moves the
    entities (same unique_ids) to the renamed device."""
    cfgs, _, _ = entities.discovery_configs(
        "n1", entities.device_info("n1", SERIAL), "franklinwh-local", "homeassistant")
    topics = [c[0] for c in cfgs]
    assert all("/n1/" in t for t in topics)
    assert all(t.startswith("homeassistant/") for t in topics)


# -- removing a gateway takes its entities with it ----------------------------------------
# Cross-bridge audit, 2026-10-15: "adding, removing or disabling a gateway … with no
# orphaned entities?" Ours stopped the publisher without clearing discovery, so a deleted
# gateway's entities stayed in Home Assistant for ever — a retained config outlives the
# bridge and HA has nothing that expires it.

def test_deleting_a_gateway_asks_for_its_entities_to_be_cleared(client, monkeypatch):
    from franklinwh_direct_connect_bridge import state
    st = db.get_store(None)
    st.create_gateway(gw_id="g1", label="aGate", host="192.0.2.110")
    state.reset_gateways()
    gw = state.register_gateway("g1", "192.0.2.110", "aGate")
    r = client.delete("/api/gateways/g1")
    assert r.status_code in (200, 204), r.text
    assert gw.unpublish_on_stop is True
    state.reset_gateways()


def test_a_normal_restart_does_not_wipe_entities():
    """The flag defaults off: clearing on every add-on restart would be far worse than
    leaving a stale entity behind."""
    from franklinwh_direct_connect_bridge import state
    state.reset_gateways()
    gw = state.register_gateway("g2", "192.0.2.110", "aGate")
    assert gw.unpublish_on_stop is False
    state.reset_gateways()
