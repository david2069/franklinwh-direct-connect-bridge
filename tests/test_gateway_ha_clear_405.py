"""#405 — disabling or deleting a gateway removes its entities from Home Assistant.

Discovery configs are retained, so a gateway whose publisher was just stopped stayed in
HA for good. Disable and delete now remove its retained topics (the same verified purge
as Unpublish). Nothing else does: a restart or a reconcile that keeps it enabled leaves
them alone."""
import os

import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import app as app_module
from franklinwh_direct_connect_bridge import config, db, supervisor, mockgw
from franklinwh_direct_connect_bridge import client as client_module
from franklinwh_direct_connect_bridge.publish import purge


@pytest.fixture
def gw_client(tmp_path, monkeypatch):
    store = db.MetricsStore(os.path.join(str(tmp_path), "m.db"))
    monkeypatch.setattr(db, "get_store", lambda *a, **k: store)

    async def _noop(*a, **k):
        return None
    monkeypatch.setattr(supervisor, "start_poller", _noop)
    monkeypatch.setattr(supervisor, "stop_poller", _noop)
    monkeypatch.setattr(supervisor, "is_running", lambda gid: False)
    monkeypatch.setattr(mockgw, "start_mock", lambda gid, **k: "127.0.0.1:59999")
    monkeypatch.setattr(mockgw, "stop_mock", lambda gid: None)
    monkeypatch.setattr(client_module, "writes_enabled", lambda s: True)
    monkeypatch.setattr(config.get_settings(), "mqtt_enabled", True)
    purged = []

    def _purge(settings, node, **k):
        purged.append(node)
        return {"ok": True, "node": node, "found": 3, "removed": 3, "left": []}
    monkeypatch.setattr(purge, "purge", _purge)
    c = TestClient(app_module.create_app())
    return c, store, purged


def _add_two(c, store):
    """A default gateway plus a second one with a serial (the one under test)."""
    assert c.post("/api/gateways", json={"label": "Home", "host": "192.0.2.10"}).status_code == 201
    gid = c.post("/api/gateways", json={"label": "Shed", "host": "192.0.2.11",
                                        "enabled": True}).json()["id"]
    store.lock_gateway_serial(gid, "TESTSERIAL01")
    return gid


def test_disable_clears_its_ha_entities(gw_client):
    c, store, purged = gw_client
    gid = _add_two(c, store)
    assert c.patch(f"/api/gateways/{gid}", json={"enabled": False}).status_code == 200
    assert purged == ["testserial01"]


def test_delete_clears_its_ha_entities(gw_client):
    c, store, purged = gw_client
    gid = _add_two(c, store)
    store.update_gateway(gid, enabled=False)     # disabled before this fix: still in HA
    assert c.delete(f"/api/gateways/{gid}").status_code == 200
    assert purged == ["testserial01"]


def test_other_changes_leave_ha_alone(gw_client):
    c, store, purged = gw_client
    gid = _add_two(c, store)
    assert c.patch(f"/api/gateways/{gid}", json={"label": "Barn"}).status_code == 200
    assert c.post(f"/api/gateways/{gid}/restart").status_code in (200, 404, 409)
    assert purged == []


def test_not_published_gateway_is_not_purged(gw_client):
    c, store, purged = gw_client
    gid = _add_two(c, store)
    store.update_gateway(gid, publish_ha=False)  # Unpublish already removed it
    assert c.patch(f"/api/gateways/{gid}", json={"enabled": False}).status_code == 200
    assert purged == []


def test_mqtt_off_is_not_purged(gw_client, monkeypatch):
    c, store, purged = gw_client
    gid = _add_two(c, store)
    monkeypatch.setattr(config.get_settings(), "mqtt_enabled", False)
    assert c.patch(f"/api/gateways/{gid}", json={"enabled": False}).status_code == 200
    assert purged == []


def test_broker_down_does_not_block_disable_or_delete(gw_client, monkeypatch):
    c, store, purged = gw_client
    gid = _add_two(c, store)

    def _down(settings, node, **k):
        raise ConnectionRefusedError("broker down")
    monkeypatch.setattr(purge, "purge", _down)
    assert c.patch(f"/api/gateways/{gid}", json={"enabled": False}).status_code == 200
    assert c.delete(f"/api/gateways/{gid}").status_code == 200
