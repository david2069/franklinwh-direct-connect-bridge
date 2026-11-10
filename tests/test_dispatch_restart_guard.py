"""#175: the guarded worker-restart refuses while this bridge holds a force.

battery_control.current() reports the force under ``active`` ("Not Active" when idle);
the guard used to read ``command``, which current() never returns. It also named
battery_control without importing it, so the NameError made it refuse every restart
("cannot determine dispatch state"), force or not.
"""
import time

from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import app as app_module
from franklinwh_direct_connect_bridge import battery_control
from franklinwh_direct_connect_bridge import workers as W

NAME = "dispatch:guard-test"


def _restart(client):
    return client.post(f"/api/health/workers/{NAME}/restart")


def _register(calls):
    def factory():
        calls.append(1)
    W.registry.register(W.Worker(name=NAME, concern="test", cadence_s=5.0, kind="task",
                                 restart_class=W.RestartClass.GUARDED, factory=factory))


def test_restart_is_refused_while_a_force_is_active():
    calls = []
    client = TestClient(app_module.create_app())
    _register(calls)
    battery_control._active["h"] = {"command": "Force Discharge", "host": "h",
                                    "started": time.time()}
    try:
        r = _restart(client)
        assert r.status_code == 409
        assert "force active (Force Discharge)" in r.json()["detail"]
        assert calls == []
    finally:
        battery_control._active.clear()
        W.registry.unregister(NAME)


def test_restart_is_allowed_with_no_force():
    calls = []
    client = TestClient(app_module.create_app())
    _register(calls)
    try:
        assert battery_control.current() == {"active": "Not Active"}
        r = _restart(client)
        assert r.status_code == 200, r.text
        assert calls == [1]
    finally:
        W.registry.unregister(NAME)
