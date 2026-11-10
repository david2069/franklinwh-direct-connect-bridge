"""#93 — idle workers must not be reported as failed.

The three thread workers (vpp-monitor, cloud-status, dispatch-watchdog) beat once at
registration and never again, so the supervisor declared each "unresponsive" every few
minutes and the audit trail filled with worker_failed. With no cloud credentials the cloud
loop exits by design — that is "paused", not "failed".
"""
import time

from franklinwh_direct_connect_bridge import battery_control, workers
from franklinwh_direct_connect_bridge.workers import Worker, WorkerState, RestartClass


def _reg(name, state=WorkerState.RUNNING, cadence=30.0):
    w = workers.registry.register(Worker(name=name, concern="t", cadence_s=cadence,
                                         restart_class=RestartClass.FREE, kind="thread"))
    w.beat(state=state)
    return w


def _age(w, seconds):
    w.last_beat_ts = time.time() - seconds


def test_a_paused_worker_is_never_stale():
    w = _reg("t-paused", WorkerState.PAUSED)
    _age(w, 10_000)
    seen = []
    workers._supervise_once(workers.registry, on_transition=lambda w, r: seen.append(w.name))
    assert "t-paused" not in seen and w.state is WorkerState.PAUSED
    workers.registry.unregister("t-paused")


def test_a_running_worker_that_stops_beating_is_still_caught():
    """The supervisor's purpose is kept: silence while RUNNING is still a failure."""
    w = _reg("t-silent", WorkerState.RUNNING)
    _age(w, 10_000)
    seen = []
    workers._supervise_once(workers.registry, on_transition=lambda w, r: seen.append(w.name))
    assert "t-silent" in seen
    workers.registry.unregister("t-silent")


def test_the_dispatch_watchdog_pauses_when_its_force_ends(monkeypatch):
    w = _reg("dispatch-watchdog", WorkerState.PAUSED)
    monkeypatch.setattr(battery_control, "_watch", lambda *a, **k: None)   # force ends at once
    with battery_control._lock:
        battery_control._active.clear()
    battery_control._watchdog_loop("192.0.2.1", 1.0, 0, 0, 100)
    assert w.state is WorkerState.PAUSED and w.detail == "no force active"
    workers.registry.unregister("dispatch-watchdog")


def test_the_dispatch_watchdog_beats_while_a_force_is_active(monkeypatch):
    w = _reg("dispatch-watchdog", WorkerState.PAUSED)
    states = []
    monkeypatch.setattr(battery_control, "_watch",
                        lambda *a, **k: states.append(w.state))
    battery_control._watchdog_loop("192.0.2.1", 1.0, 0, 0, 100)
    assert states == [WorkerState.RUNNING]
    workers.registry.unregister("dispatch-watchdog")


def test_app_start_registers_workers_paused_or_beating(monkeypatch):
    """No credentials: cloud-status ends PAUSED with a reason, not RUNNING-and-silent."""
    from fastapi.testclient import TestClient
    from franklinwh_direct_connect_bridge import app as app_module, config
    s = config.get_settings()
    monkeypatch.setattr(s, "fwh_cloud_email", "")
    monkeypatch.setattr(s, "fwh_cloud_password", "")
    with TestClient(app_module.create_app()):
        deadline = time.time() + 5
        while time.time() < deadline:
            cs = workers.registry.get("cloud-status")
            if cs is not None and cs.state is WorkerState.PAUSED:
                break
            time.sleep(0.1)
        cs = workers.registry.get("cloud-status")
        assert cs is not None and cs.state is WorkerState.PAUSED
        assert "no cloud credentials" in cs.detail
        dw = workers.registry.get("dispatch-watchdog")
        assert dw is not None and dw.state is WorkerState.PAUSED
