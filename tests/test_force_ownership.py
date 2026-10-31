"""A force belongs to the schedule that started it (#189, #191, #195, #196, #197, #199)."""
import datetime as dt

import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import app as app_module
from franklinwh_direct_connect_bridge import battery_control as bc
from franklinwh_direct_connect_bridge import config, db
from franklinwh_direct_connect_bridge import scheduler as sch
from franklinwh_direct_connect_bridge.db import MetricsStore

T0 = dt.datetime(2026, 10, 28, 14, 30)
FORCE = {"kind": "force", "direction": "discharge", "unit": "pct", "power": 50}


@pytest.fixture(autouse=True)
def _fresh():
    for d in (sch._window_inside, sch._window_key, sch._gated_day, sch._dwell_since):
        d.clear()
    yield


@pytest.fixture
def st(tmp_path):
    return MetricsStore(str(tmp_path / "m.db"))


@pytest.fixture
def sent(monkeypatch):
    out = []
    monkeypatch.setattr(bc, "execute", lambda cmd, **kw: (out.append(cmd), {
        "ok": True, "result": "ok", "active": cmd})[1])
    return out


def _tick(st, now=T0, soc=50):
    return sch.tick(settings=None, client=None, store=st, state={"soc": soc}, host="h",
                    gateway_id="gw-h", now=now)


def _sched(st, sid, *, prio=0, conflict="override", conds=None, fire_at="14:00", dur=60):
    st.create_schedule(sid=sid, name=f"rule-{sid}", spec={"gateway_id": "gw-h",
        "fire_at": fire_at, "duration_min": dur, "priority": prio, "conflict": conflict,
        "conditions": conds or [], "action": dict(FORCE)})


# ── #191 ─────────────────────────────────────────────────────────────────────

def test_a_refused_force_is_a_failed_run_not_fired(st, monkeypatch):
    monkeypatch.setattr(bc, "execute", lambda cmd, **kw: {
        "ok": False, "result": "This bridge's Modbus client is off", "state": "not_configured"})
    _sched(st, "a")
    fired = _tick(st)
    assert fired[0]["ok"] is False
    assert not st.schedule("a").get("last_fired_day")
    assert [e["status"] for e in st.schedule_log(schedule_id="a")][0] == "error"


def test_a_rejected_mode_write_is_a_failed_run(st, monkeypatch):
    class Client:
        def set_mode(self, settings, mode, host=None):
            return {"ok": False, "result": 3}       # rejected; no "error" word in it
    st.create_schedule(sid="m", name="mode", spec={"gateway_id": "gw-h",
        "fire_at": "14:00", "duration_min": 60, "action": {"kind": "set_mode", "mode": "self"}})
    fired = sch.tick(settings=None, client=Client(), store=st, state={"soc": 50}, host="h",
                     gateway_id="gw-h", now=T0)
    assert fired[0]["ok"] is False and "failed" in fired[0]["result"]


# ── #197 ─────────────────────────────────────────────────────────────────────

def test_a_failing_scheduled_write_never_sleeps_inside_the_tick(st, monkeypatch):
    from franklinwh_direct_connect_bridge import resilience
    slept = []
    monkeypatch.setattr(resilience.time, "sleep", lambda s: slept.append(s))

    class Client:
        def set_mode(self, settings, mode, host=None):
            raise ConnectionError("aGate unreachable")
    st.create_schedule(sid="m", name="mode", spec={"gateway_id": "gw-h",
        "fire_at": "14:00", "duration_min": 60, "action": {"kind": "set_mode", "mode": "self"}})
    fired = sch.tick(settings=None, client=Client(), store=st, state={"soc": 50}, host="h",
                     gateway_id="gw-h", now=T0)
    assert fired[0]["ok"] is False
    assert slept == []                       # the run's own backoff retries it, not a sleep


# ── #189 ─────────────────────────────────────────────────────────────────────

def test_window_end_does_not_release_a_force_it_never_started(st, sent):
    _sched(st, "g", conds=[{"sensor": "battery.soc_pct", "op": "<", "value": 1}])
    _tick(st)                                               # gated the whole window
    _tick(st, now=T0 + dt.timedelta(minutes=45))            # window closed
    assert "Release" not in sent
    assert any("did not hold the force" in e["result"]
               for e in st.schedule_log(schedule_id="g") if e["status"] == "exit")


def test_window_end_does_not_release_a_force_another_rule_took_over(st, sent):
    _sched(st, "a", fire_at="14:00", dur=60)
    _tick(st)                                               # a fires
    _sched(st, "b", fire_at="14:40", dur=60, prio=5)
    _tick(st, now=T0 + dt.timedelta(minutes=15))           # b overrides a
    sent.clear()
    _tick(st, now=T0 + dt.timedelta(minutes=35))           # a's window closes
    assert "Release" not in sent


def test_window_end_does_not_release_a_battery_control_force_on_its_gateway(st, sent):
    st.create_schedule(sid="a", name="rule-a", spec={
        "gateway_id": "gw-a", "fire_at": "14:00", "duration_min": 60, "action": dict(FORCE)})
    sch.tick(settings=None, client=None, store=st, state={"soc": 50}, host="h",
             gateway_id="gw-a", now=T0, modbus_host="")
    # Battery Control forces the same aGate; its row carries no gateway id.
    st.record_dispatch(schedule_id="_widget", name="Battery Control (widget)", gateway_id=None,
                       host="h", direction="charge", watts=50, power_mode="pct",
                       target_soc=0, window_start_ts=1, window_end_ts=None)
    sent.clear()
    sch.tick(settings=None, client=None, store=st, state={"soc": 50}, host="h",
             gateway_id="gw-a", now=T0 + dt.timedelta(minutes=45), modbus_host="")
    assert "Release" not in sent


def test_window_end_still_releases_its_own_force(st, sent):
    _sched(st, "a")
    _tick(st)
    sent.clear()
    _tick(st, now=T0 + dt.timedelta(minutes=45))
    assert sent == ["Release"]
    assert not st.active_dispatches(host="h")


# ── #196 ─────────────────────────────────────────────────────────────────────

def test_a_lower_priority_force_does_not_override_a_running_one(st, sent):
    _sched(st, "hi", prio=9, fire_at="14:00", dur=60)
    _tick(st)
    _sched(st, "lo", prio=1, fire_at="14:40", dur=60)
    sent.clear()
    _tick(st, now=T0 + dt.timedelta(minutes=15))
    assert sent == []
    log = [e for e in st.schedule_log(schedule_id="lo") if e["status"] == "deferred"]
    assert log and "rule-hi" in log[0]["result"]


def test_a_higher_priority_force_still_overrides(st, sent):
    _sched(st, "lo", prio=1, fire_at="14:00", dur=60)
    _tick(st)
    _sched(st, "hi", prio=9, fire_at="14:40", dur=60)
    sent.clear()
    _tick(st, now=T0 + dt.timedelta(minutes=15))
    assert sent == ["Force Discharge"]


# ── #195 ─────────────────────────────────────────────────────────────────────

def test_deleting_a_running_schedule_releases_its_force(st, sent, monkeypatch):
    monkeypatch.setattr(db, "get_store", lambda s: st)
    _sched(st, "a")
    _tick(st)
    sent.clear()
    r = TestClient(app_module.create_app()).delete("/api/schedules/a").json()
    assert sent == ["Release"] and r["released"]
    assert not st.active_dispatches(host="h")


def test_deleting_an_idle_schedule_sends_nothing(st, sent, monkeypatch):
    monkeypatch.setattr(db, "get_store", lambda s: st)
    _sched(st, "a", fire_at="18:00")
    r = TestClient(app_module.create_app()).delete("/api/schedules/a").json()
    assert sent == [] and r["deleted"] == "a" and not r.get("released")


# ── #199 ─────────────────────────────────────────────────────────────────────

def test_restart_policy_defaults_to_release_and_release_stale_is_gone():
    assert config.Settings().dispatch_interrupt_policy == "release"
    assert not hasattr(bc, "release_stale")
