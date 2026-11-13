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


# -- #616: a deliberate back-off is not a stall ------------------------------------------
def test_a_worker_that_says_when_it_beats_next_is_not_stale_before_then():
    w = _reg("t-backoff", WorkerState.RUNNING, cadence=300.0)
    w.beat(next_beat_in_s=1800)
    _age(w, 1799)
    assert not w.beat_is_stale
    workers.registry.unregister("t-backoff")


def test_a_worker_that_misses_its_announced_beat_is_still_stale():
    w = _reg("t-late", WorkerState.RUNNING, cadence=300.0)
    w.beat(next_beat_in_s=1800)
    _age(w, 1800 + w.beat_grace_s + 1)
    assert w.beat_is_stale
    workers.registry.unregister("t-late")


def test_a_plain_beat_drops_the_announced_delay():
    w = _reg("t-reset", WorkerState.RUNNING, cadence=300.0)
    w.beat(next_beat_in_s=1800)
    w.beat()
    _age(w, w.beat_grace_s + 1)
    assert w.beat_is_stale
    workers.registry.unregister("t-reset")


def test_a_hung_worker_still_raises_worker_stalled():
    from franklinwh_direct_connect_bridge import alerts
    w = _reg("t-hung", WorkerState.RUNNING, cadence=300.0)
    _age(w, w.beat_grace_s + 1)
    workers._supervise_once(workers.registry, on_transition=alerts.on_worker_transition)
    f = alerts.facts().get(("", "WORKER_STALLED"))
    assert f is not None and f["bad"] and "t-hung" in f["detail"]
    workers.registry.unregister("t-hung")
    alerts.check_workers(workers.registry)


def test_a_failing_cloud_login_backing_off_raises_no_worker_stalled(monkeypatch):
    """The 0.5.39 test bridge: a cloud login that keeps failing backs off to 30 min,
    past the watchdog's 20 min, and raised WORKER_STALLED (critical) every cycle."""
    import sys
    import threading
    from fastapi.testclient import TestClient
    from franklinwh_direct_connect_bridge import alerts, app as app_module, cloud_status, \
        config, providers

    s = config.get_settings()
    monkeypatch.setattr(s, "fwh_cloud_email", "a@example.com")
    monkeypatch.setattr(s, "fwh_cloud_password", "pw")
    monkeypatch.setitem(providers._cloud_auth, "state", "unknown")

    def _fail(_s):
        cloud_status.LAST_ERROR = "FileNotFoundError: no token"
        return None
    monkeypatch.setattr(cloud_status, "poll", _fail)

    real_sleep, done, delays, stalled = time.sleep, threading.Event(), [], []

    def _sleep(sec):
        if sys._getframe(1).f_code.co_name != "_cloud_status_loop" or sec <= 8:
            return real_sleep(min(sec, 0.01) if sec <= 8 else sec)
        # A back-off: let the time pass for the watchdog, then look.
        delays.append(sec)
        cs = workers.registry.get("cloud-status")
        cs.last_beat_ts -= sec - 1
        workers._supervise_once(workers.registry,
                                on_transition=lambda w, r: stalled.append((w.name, r)))
        if len(delays) >= 3:
            done.set()
            threading.Event().wait()        # park the daemon thread
    monkeypatch.setattr(time, "sleep", _sleep)

    with TestClient(app_module.create_app()):
        assert done.wait(10), delays
    assert max(delays) > workers.registry.get("cloud-status").beat_grace_s
    assert not [x for x in stalled if x[0] == "cloud-status"], stalled
    f = alerts.facts().get(("", "WORKER_STALLED"))
    assert f is None or "cloud-status" not in f["detail"]
