"""#711 (owner 2026-11-17): an entity is published only while its source is set up and
active, and follows it live. Every entity and control carries a ``source`` — ``local``
(the Direct Connect API), ``cloud`` (the FranklinWH cloud) or ``modbus`` (this bridge's
Modbus client) — which decides when it is published and is documented as the Source
column. A mock gateway is never published to Home Assistant.
"""
import json
import pathlib
import re

import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import battery_control, config, db, poller, state
from franklinwh_direct_connect_bridge.publish import entities
from franklinwh_direct_connect_bridge.publish.mqtt_publisher import MqttPublisher

ROOT = pathlib.Path(__file__).resolve().parents[1]
PKG = ROOT / "src" / "franklinwh_direct_connect_bridge"
ALL = entities.ENTITIES + entities.CONTROLS


def test_every_entity_and_control_names_its_source():
    for e in ALL:
        assert e.get("source") in entities.SOURCES, e["key"]
    src = {e["key"]: e["source"] for e in ALL}
    # the reserve numbers write through the cloud (C2), and the TOU schedule is read from
    # it (#421); Battery Command runs over Modbus
    assert {k for k, v in src.items() if v == "cloud"} == set(entities.RESERVE_KEYS
                                                              | entities.TOU_KEYS)
    assert {k for k, v in src.items() if v == "modbus"} == set(entities.BATTERY_KEYS)
    # the aGate's own network reads, its cloud link included, are local reads
    assert src["net_cloud"] == "local" and src["operating_mode"] == "local"


def test_skip_follows_which_sources_are_active():
    both_off = entities.source_skip(cloud=False, modbus=False)
    cloud = entities.RESERVE_KEYS | entities.TOU_KEYS
    assert both_off == cloud | entities.BATTERY_KEYS
    assert entities.source_skip(cloud=True, modbus=True) == frozenset()
    assert entities.source_skip(cloud=True, modbus=False) == entities.BATTERY_KEYS
    assert entities.source_skip(cloud=False, modbus=True) == cloud


class _Client:
    def __init__(self):
        self.sent = []

    def publish(self, topic, payload, retain=False):
        self.sent.append((topic, payload))


def _pub(skip):
    s = config.Settings()
    p = MqttPublisher(s, "n1", {}, groups=list(entities.GROUPS), skip=skip)
    p.client = _Client()
    return p


def test_a_source_that_turns_on_adds_its_entities_and_one_that_turns_off_removes_them():
    p = _pub(entities.BATTERY_KEYS)
    assert not any("battery_command" in t for t, _ in p.configs)
    p.set_skip(frozenset())                         # Modbus client switched on
    added = [t for t, body in p.client.sent if body]
    assert added and all("battery_command" in t for t in added)
    assert not [t for t, body in p.client.sent if body == ""]
    p.client.sent.clear()
    p.set_skip(entities.BATTERY_KEYS)               # ...and off again
    cleared = [t for t, body in p.client.sent if body == ""]
    assert len(cleared) == len(entities.BATTERY_KEYS)
    assert all("battery_command" in t for t in cleared)
    assert not [t for t, body in p.client.sent if body]     # nothing else re-sent
    p.client.sent.clear()
    p.set_skip(entities.BATTERY_KEYS)               # no change, nothing sent
    assert p.client.sent == []


def test_the_poller_gates_battery_command_on_the_modbus_client(monkeypatch):
    s = config.Settings()
    gw = state.GatewayState(id="g", serial="SN1", serial_locked=True)
    monkeypatch.setattr(battery_control, "_ENABLED", False)
    assert entities.BATTERY_KEYS <= poller.ha_skip(s, gw)
    monkeypatch.setattr(battery_control, "_ENABLED", True)
    assert not entities.BATTERY_KEYS & poller.ha_skip(s, gw)
    # cloud: only with credentials for this gateway
    assert entities.RESERVE_KEYS <= poller.ha_skip(s, gw)
    monkeypatch.setattr(s, "fwh_cloud_email", "e")
    monkeypatch.setattr(s, "fwh_cloud_password", "p")
    assert not entities.RESERVE_KEYS & poller.ha_skip(s, gw)
    assert "pub.set_skip, ha_skip(settings, gw)" in (PKG / "poller.py").read_text()  # every cycle


# ── Mocks are never published ─────────────────────────────────────────────────────

def test_a_mock_gateway_never_publishes():
    gw = state.register_gateway("m711", "127.0.0.1:1", "Mock", is_mock=True, publish_ha=True)
    try:
        assert gw.publish_ha is False
    finally:
        state.unregister_gateway("m711")


@pytest.fixture
def client(tmp_path, monkeypatch):
    from franklinwh_direct_connect_bridge import app as app_module, mockgw, supervisor
    state.reset_gateways()
    store = db.MetricsStore(str(tmp_path / "m.db"))
    monkeypatch.setattr(db, "get_store", lambda *a, **k: store)
    monkeypatch.setattr(mockgw, "start_mock", lambda *a, **k: "127.0.0.1:1")
    monkeypatch.setattr(mockgw, "stop_mock", lambda *a, **k: None)

    async def _noop(*a, **k):
        return None
    monkeypatch.setattr(supervisor, "start_poller", _noop)
    monkeypatch.setattr(supervisor, "stop_poller", _noop)
    s = config.get_settings()
    monkeypatch.setattr(s, "allow_writes", True)
    monkeypatch.setattr(s, "mqtt_enabled", True)
    yield TestClient(app_module.create_app()), store
    state.reset_gateways()


def test_the_api_keeps_a_mock_unpublished(client):
    c, store = client
    r = c.post("/api/gateways", json={"label": "Mock", "is_mock": True, "publish_ha": True})
    assert r.status_code == 201, r.text
    gid = r.json()["id"]
    assert not store.gateway(gid)["publish_ha"]
    r = c.patch(f"/api/gateways/{gid}", json={"publish_ha": True})
    assert r.status_code == 422 and "mock" in r.text.lower()
    r = c.post(f"/api/mqtt/republish?gateway={gid}").json()
    assert r["ok"] is False and "mock" in r["detail"].lower()
    assert not store.gateway(gid)["publish_ha"]


def test_the_mock_forms_have_no_publish_switch():
    html = (PKG / "templates" / "tabs" / "settings.html").read_text()
    assert "mockForm.publish_ha" not in html
    m = re.search(r'<div[^>]*x-show="!gwEdit.is_mock"[^>]*>\s*<span>Publish to Home Assistant '
                  r'\(MQTT\)</span>', html)
    assert m, "the edit dialog's switch shows for real gateways only"
    js = (PKG / "static" / "js" / "settings_tab.js").read_text()
    assert "publish_ha: this.mockForm.publish_ha" not in js


# ── Docs: the Source column ───────────────────────────────────────────────────────

def test_the_docs_tables_give_each_entitys_source():
    doc = (ROOT / "docs" / "guide" / "home-assistant.md").read_text()
    src = {e["key"]: e["source"] for e in ALL}
    seen = set()
    for line in doc.splitlines():
        if not line.startswith("| `"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        keys = re.findall(r"`([a-z0-9_]+)`", cells[0])
        known = [k for k in keys if k in src]
        if not known:
            continue
        for k in known:
            assert cells[-1] == src[k], (k, cells[-1])
            seen.add(k)
        # a range row (circuit_1_… … circuit_3_…) covers the keys between
    ranged = {k for k in src if re.match(r"circuit_2_", k)}
    assert set(src) - seen <= ranged, sorted(set(src) - seen - ranged)
