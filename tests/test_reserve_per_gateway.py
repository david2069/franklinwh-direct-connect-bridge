"""The reserve write goes to the viewed gateway's serial, or is refused (#351)."""
import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import app as app_module
from franklinwh_direct_connect_bridge import client as client_module
from franklinwh_direct_connect_bridge import config, db, providers, state


class _Store:
    def __init__(self):
        self.rows = []

    def log_control_event(self, action, **kw):
        self.rows.append({"action": action, **kw})

    def __getattr__(self, name):          # every other store call is a no-op here
        return lambda *a, **k: None


@pytest.fixture
def env(monkeypatch):
    state.reset_gateways()
    monkeypatch.setattr(client_module, "writes_enabled", lambda s: True)
    monkeypatch.setattr(providers, "cloud_auth_status", lambda: {"state": "valid", "error": None})
    monkeypatch.setattr(providers, "_lib_available", lambda m: True)
    monkeypatch.setattr(providers, "guard_login", lambda *a, **k: None)
    monkeypatch.setattr(providers, "note_login_result", lambda *a, **k: None)
    monkeypatch.setattr(providers, "_note_auth_success", lambda *a, **k: None)
    written = []
    monkeypatch.setattr(providers, "_cloud_set_reserve",
                        lambda email, pw, gw, wm, soc: written.append(gw)
                        or {"cloud": {"result": 0}, "prior": None})
    store = _Store()
    monkeypatch.setattr(db, "get_store", lambda s: store)
    monkeypatch.setenv("FWH_CLOUD_EMAIL", "a@b.c")
    monkeypatch.setenv("FWH_CLOUD_PASSWORD", "x")
    monkeypatch.delenv("FWH_CLOUD_GATEWAY", raising=False)
    monkeypatch.setattr(config, "_settings", None)
    a = state.register_gateway("gw-a", "10.0.0.1", "A")
    b = state.register_gateway("gw-b", "10.0.0.2", "B")
    a.serial, b.serial = "SERIALA", "serialb"
    state.set_default("gw-a")
    yield {"written": written, "store": store, "a": a, "b": b, "mp": monkeypatch}
    monkeypatch.setattr(config, "_settings", None)
    state.reset_gateways()


def _post(gateway=None):
    q = f"?gateway={gateway}" if gateway else ""
    return TestClient(app_module.create_app()).post(f"/api/cloud/reserve{q}",
                                                    json={"mode": "self", "soc": 20})


def test_the_reserve_goes_to_the_viewed_gateways_serial(env):
    r = _post("gw-b")
    assert r.status_code == 200, r.text
    assert env["written"] == ["SERIALB"]
    assert env["store"].rows[-1]["gateway_id"] == "gw-b"


def test_no_gateway_means_the_default(env):
    assert _post().status_code == 200
    assert env["written"] == ["SERIALA"]
    assert env["store"].rows[-1]["gateway_id"] == "gw-a"


def test_refused_when_the_cloud_credentials_are_for_another_gateway(env):
    env["mp"].setenv("FWH_CLOUD_GATEWAY", "seriala")
    env["mp"].setattr(config, "_settings", None)
    r = _post("gw-b")
    assert r.status_code == 409
    assert "different gateway" in r.json()["detail"]
    assert env["written"] == []
    row = env["store"].rows[-1]
    assert row["gateway_id"] == "gw-b" and row["ok"] is False
    assert _post("gw-a").status_code == 200       # case doesn't matter
    assert env["written"] == ["SERIALA"]


def test_refused_for_a_mock_gateway_and_an_unread_serial(env):
    m = state.register_gateway("mock", "127.0.0.1", "Mock", is_mock=True)
    m.serial = "MOCK1"
    r = _post("mock")
    assert r.status_code == 409 and "mock gateway" in r.json()["detail"]
    env["b"].serial = None
    r = _post("gw-b")
    assert r.status_code == 409 and "serial" in r.json()["detail"]
    assert env["written"] == []


def test_unknown_gateway_is_404(env):
    assert _post("nope").status_code == 404
    assert env["written"] == []
