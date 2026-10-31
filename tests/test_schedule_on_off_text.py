"""#188 — a schedule's On/Off choice must reach the device the right way round.

The editor's On/Off picker stores the TEXT "true"/"false" and the engine did
``bool(action["on"])``; ``bool("false")`` is True. A schedule set to turn a smart circuit
Off turned it On, and one set to reconnect to the grid sent go-off-grid."""
import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import state
from franklinwh_direct_connect_bridge import app as app_module, client as client_module
from franklinwh_direct_connect_bridge import scheduler as sch
from franklinwh_direct_connect_bridge.config import Settings


class FakeClient:
    def __init__(self):
        self.calls = []

    def set_smart_circuit(self, settings, circuit, on, host=None):
        self.calls.append(("circuit", circuit, on))
        return {"confirmed": True}

    def set_offgrid(self, settings, on, soc=5, host=None):
        self.calls.append(("offgrid", on))
        return {"ok": True}


def _run(action):
    fc = FakeClient()
    out = sch.run_action(action, settings=Settings(), client=fc, store=None, snapshot={})
    return fc.calls, out


@pytest.mark.parametrize("off", ["false", "False", "off", "0", False, 0])
def test_off_turns_a_smart_circuit_off(off):
    calls, out = _run({"kind": "smart_circuit", "circuit": "1", "on": off})
    assert calls == [("circuit", 1, False)]
    assert "-> off" in out


@pytest.mark.parametrize("on", ["true", "on", "1", True, 1])
def test_on_turns_a_smart_circuit_on(on):
    calls, _ = _run({"kind": "smart_circuit", "circuit": 2, "on": on})
    assert calls == [("circuit", 2, True)]


def test_reconnect_does_not_go_off_grid():
    calls, _ = _run({"kind": "offgrid", "on": "false"})
    assert calls == [("offgrid", False)]


@pytest.mark.parametrize("bad", ["", "maybe", None, 2, "yes please"])
def test_an_unreadable_value_writes_nothing(bad):
    for kind in ("smart_circuit", "offgrid"):
        calls, out = _run({"kind": kind, "circuit": 1, "on": bad})
        assert calls == [], (kind, bad)
        assert "fail" in out.lower() or "error" in out.lower(), out


@pytest.fixture
def c(monkeypatch):
    monkeypatch.setattr(client_module, "writes_enabled", lambda s: True)
    state.reset_gateways()
    state.register_gateway("g1", "192.0.2.10", "first")    # a schedule names its gateway (#379)
    yield TestClient(app_module.create_app())
    state.reset_gateways()


def _get(c, sid):
    return next(x for x in c.get("/api/schedules").json()["schedules"] if x["id"] == sid)


def test_a_saved_schedule_stores_a_real_boolean(c):
    body = {"name": "Pool pump off", "enabled": False, "fire_at": "22:00",
            "action": {"kind": "smart_circuit", "circuit": "1", "on": "false"},
            "gateway_id": "g1"}
    r = c.post("/api/schedules", json=body)
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    assert _get(c, sid)["action"]["on"] is False
    r = c.put(f"/api/schedules/{sid}", json={**body, "action": {**body["action"], "on": "true"}})
    assert r.status_code == 200, r.text
    assert _get(c, sid)["action"]["on"] is True


def test_saving_an_unreadable_on_value_is_refused(c):
    r = c.post("/api/schedules", json={"name": "x", "enabled": False, "fire_at": "22:00",
                                       "action": {"kind": "offgrid", "on": "maybe"}})
    assert r.status_code == 422
