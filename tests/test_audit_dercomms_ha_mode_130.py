"""#130: the Audit trail records the aGate Modbus TCP Server (:502) switch
(POST /api/der-comms) and an operating-mode change from the Home Assistant select."""
import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import app as app_module
from franklinwh_direct_connect_bridge import client as client_module
from franklinwh_direct_connect_bridge import db, state
from franklinwh_direct_connect_bridge.publish import handle_command

GW = "gw-130"


class _Store:
    def __init__(self):
        self.rows = []

    def log_control_event(self, action, **kw):
        self.rows.append((action, kw))

    def __getattr__(self, name):
        return lambda *a, **k: None


@pytest.fixture
def store(monkeypatch):
    st = _Store()
    monkeypatch.setattr(db, "get_store", lambda s=None: st)
    state.register_gateway(GW, "10.0.0.1", "Test")
    yield st
    state.unregister_gateway(GW)


def test_der_comms_is_audited(store, monkeypatch):
    monkeypatch.setattr(client_module, "writes_enabled", lambda s: True)
    monkeypatch.setattr(client_module, "set_der_comms", lambda *a, **k: {"ok": True})
    r = TestClient(app_module.create_app()).post(f"/api/der-comms?gateway={GW}",
                                                  json={"sunspec_modbus": True})
    assert r.status_code == 200
    row = [kw for a, kw in store.rows if a == "der_comms"]
    assert row and row[0]["gateway_id"] == GW and row[0]["ok"] is True
    assert "sunspec_modbus=on" in row[0]["detail"]


def test_a_failed_der_comms_write_is_audited_as_failed(store, monkeypatch):
    monkeypatch.setattr(client_module, "writes_enabled", lambda s: True)
    def boom(*a, **k):
        raise TimeoutError("no answer")
    monkeypatch.setattr(client_module, "set_der_comms", boom)
    r = TestClient(app_module.create_app()).post(f"/api/der-comms?gateway={GW}",
                                                  json={"ieee2030_5": False})
    assert r.status_code == 502
    row = [kw for a, kw in store.rows if a == "der_comms"]
    assert row and row[0]["ok"] is False and "no answer" in row[0]["result"]


class _Client:
    def __init__(self, out):
        self.out = out

    def set_mode(self, settings, mode, host=None):
        return self.out


def test_a_mode_change_from_home_assistant_is_audited(store):
    gw = state.get_gateway(GW)
    out = handle_command("operating_mode", "Self-Consumption", settings=None,
                         client=_Client({"ok": True}), gateway=gw, store=store)
    assert out.endswith(": ok")
    (action, kw), = store.rows
    assert action == "set_mode" and kw["source"] == "ha" and kw["gateway_id"] == GW
    assert kw["ok"] is True and "Self-Consumption" in kw["detail"]


def test_a_rejected_mode_change_from_home_assistant_is_audited_as_failed(store):
    handle_command("operating_mode", "Self-Consumption", settings=None,
                   client=_Client({"ok": False, "result": 3}),
                   gateway=state.get_gateway(GW), store=store)
    (action, kw), = store.rows
    assert kw["ok"] is False
