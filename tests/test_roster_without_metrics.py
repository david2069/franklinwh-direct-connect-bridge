"""#81 — the gateway roster must work when metric history is off.

The roster, setup state and settings share the SQLite store with metric history. When
``metrics_active`` turned the store off (the add-on default with MQTT on, since 0.3.3),
``get_store`` returned None and adding any gateway answered 503 "metrics store is disabled;
gateway roster needs it" — a fresh add-on install could not be set up.

Unlike test_gateway_roster.py, these tests do NOT stub ``db.get_store``: stubbing it is
exactly why the defect was never caught.
"""
import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import app as app_module
from franklinwh_direct_connect_bridge import config, db, environment, mockgw, supervisor


@pytest.fixture
def no_side_effects(monkeypatch):
    async def _noop(*a, **k):
        return None
    monkeypatch.setattr(supervisor, "start_poller", _noop)
    monkeypatch.setattr(supervisor, "stop_poller", _noop)
    monkeypatch.setattr(supervisor, "is_running", lambda gid: False)
    monkeypatch.setattr(mockgw, "start_mock", lambda gid, **k: "127.0.0.1:59999")
    monkeypatch.setattr(mockgw, "stop_mock", lambda gid: None)


def _metrics_off_explicit(monkeypatch):
    s = config.get_settings()
    monkeypatch.setattr(s, "metrics_enabled", False)
    return s


def _metrics_off_addon_default(monkeypatch):
    """The fresh add-on install: add-on runtime, MQTT on, metrics_enabled unset."""
    s = config.get_settings()
    monkeypatch.setattr(environment, "IS_HA_ADDON", True)
    monkeypatch.setattr(s, "mqtt_enabled", True)
    monkeypatch.setattr(s, "metrics_enabled", None)
    return s


@pytest.mark.parametrize("setup", [_metrics_off_explicit],
                         ids=["metrics_enabled=false"])
def test_store_opens_even_when_metrics_are_off(monkeypatch, setup):
    s = setup(monkeypatch)
    assert config.metrics_active(s) is False   # the premise: history recording is off
    assert db.get_store(s) is not None         # ...but the roster's store is still there


@pytest.mark.parametrize("setup", [_metrics_off_explicit, _metrics_off_addon_default],
                         ids=["metrics_enabled=false", "addon+mqtt default"])
def test_gateways_can_be_added_edited_and_removed_with_metrics_off(
        monkeypatch, no_side_effects, setup):
    setup(monkeypatch)
    c = TestClient(app_module.create_app())

    r = c.post("/api/gateways", json={"label": "Mock 1", "is_mock": True})
    assert r.status_code == 201, r.text
    gid = r.json()["id"]

    r = c.post("/api/gateways", json={"label": "Home", "host": "192.0.2.10"})
    assert r.status_code == 201, r.text

    ids = {g["id"] for g in c.get("/api/gateways").json()}
    assert gid in ids and len(ids) == 2

    assert c.patch(f"/api/gateways/{gid}", json={"label": "Renamed"}).status_code == 200
    # Mock 1 was created first, so it is the default (#182): make Home the default, then
    # disable Mock 1 before removing it (#146).
    home = next(g["id"] for g in c.get("/api/gateways").json() if g["id"] != gid)
    assert c.post(f"/api/gateways/{home}/default").status_code == 200
    assert c.patch(f"/api/gateways/{gid}", json={"enabled": False}).status_code == 200
    assert c.delete(f"/api/gateways/{gid}").status_code == 200
    assert gid not in {g["id"] for g in c.get("/api/gateways").json()}


def test_metrics_switch_still_reported_off(monkeypatch, no_side_effects):
    """Explicitly off stays off: the store is open for the roster, recording is not."""
    _metrics_off_explicit(monkeypatch)
    c = TestClient(app_module.create_app())
    assert c.get("/api/settings").json()["metrics"]["enabled"] is False


def test_addon_default_records_history(monkeypatch, no_side_effects):
    """#136: a fresh add-on install (MQTT on, metrics unset) records history again."""
    _metrics_off_addon_default(monkeypatch)
    c = TestClient(app_module.create_app())
    assert c.get("/api/settings").json()["metrics"]["enabled"] is True
