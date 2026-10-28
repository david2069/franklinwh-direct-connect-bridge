"""Forces on a multi-gateway site act on their own aGate (#192, #193, #194, #270)."""
import datetime as dt
import time

import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import app as app_module
from franklinwh_direct_connect_bridge import battery_control as bc
from franklinwh_direct_connect_bridge import db, state
from franklinwh_direct_connect_bridge import scheduler as sch
from franklinwh_direct_connect_bridge.db import MetricsStore

T0 = dt.datetime(2026, 10, 28, 14, 30)
FORCE = {"kind": "force", "direction": "discharge", "unit": "pct", "power": 50}


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    for d in (sch._window_inside, sch._window_key, sch._gated_day, sch._dwell_since):
        d.clear()
    monkeypatch.setattr(bc, "_watch", lambda *a, **k: None)   # no real watchdog threads
    bc._clear_active()
    yield
    bc._clear_active()


@pytest.fixture
def st(tmp_path):
    return MetricsStore(str(tmp_path / "m.db"))


@pytest.fixture
def sent(monkeypatch):
    out = []
    monkeypatch.setattr(bc, "execute", lambda cmd, **kw: (out.append((cmd, kw.get("host"))), {
        "ok": True, "result": "ok", "active": cmd})[1])
    return out


class _Gw:
    def __init__(self, gid, host, soc):
        self.id, self.active_host, self.configured_host = gid, host, host
        self.last_state, self.is_mock = {"soc": soc}, False


# ── #194 ─────────────────────────────────────────────────────────────────────

def test_a_second_gateways_force_keeps_the_first_ones_limits():
    bc._arm_watchdog("10.0.0.1", "Force Charge", 2000, 600, 90)
    bc._arm_watchdog("10.0.0.2", "Force Discharge", -1000, 300, 20)
    a, b = bc.current("10.0.0.1"), bc.current("10.0.0.2")
    assert (a["active"], a["duration_s"], a["target_soc"]) == ("Force Charge", 600, 90)
    assert (b["active"], b["duration_s"], b["target_soc"]) == ("Force Discharge", 300, 20)
    assert bc.holds_force("10.0.0.1") and bc.holds_force("10.0.0.2:502")
    assert sorted(bc.held_hosts()) == ["10.0.0.1", "10.0.0.2"]


def test_each_force_keeps_its_own_soc_reader():
    bc._arm_watchdog("10.0.0.1", "Force Charge", 2000, 0, 90, soc_getter=lambda: 11)
    bc._arm_watchdog("10.0.0.2", "Force Discharge", -1000, 0, 20, soc_getter=lambda: 77)
    assert bc._active["10.0.0.1"]["soc_getter"]() == 11
    assert bc._active["10.0.0.2"]["soc_getter"]() == 77


def test_the_watchdog_releases_only_its_own_gateway(monkeypatch):
    monkeypatch.setattr(bc, "_connect", lambda h: (type("C", (), {
        "reset_control_state": lambda s: None, "disconnect": lambda s: None})(), None))
    bc._arm_watchdog("10.0.0.1", "Force Charge", 2000, 1, 0)
    bc._arm_watchdog("10.0.0.2", "Force Discharge", -1000, 0, 0)
    bc._release_now("10.0.0.1", bc._active["10.0.0.1"]["key"], "duration 1s reached")
    assert bc.held_hosts() == ["10.0.0.2"]


# ── #192 ─────────────────────────────────────────────────────────────────────

def _two_gateways(monkeypatch):
    gws = [_Gw("gw-a", "10.0.0.1", 40), _Gw("gw-b", "10.0.0.2", 80)]
    monkeypatch.setattr(state, "gateways", lambda: gws)
    return gws


def test_stop_releases_the_gateway_the_force_was_sent_to(st, sent, monkeypatch):
    _two_gateways(monkeypatch)
    monkeypatch.setattr(db, "get_store", lambda s: st)
    st.create_schedule(sid="b", name="on b", spec={"gateway_id": "gw-b", "fire_at": "14:00",
                                                  "duration_min": 60, "action": dict(FORCE)})
    st.record_dispatch(schedule_id="b", name="on b", gateway_id="gw-b", host="10.0.0.2",
                       direction="discharge", watts=-50, power_mode="pct", target_soc=0,
                       window_start_ts=1, window_end_ts=None)
    c = TestClient(app_module.create_app())
    assert c.post("/api/schedules/b/stop").json()["stopped"] is True
    assert sent == [("Release", "10.0.0.2")]


def test_boot_reconcile_covers_every_gateway_with_its_own_soc(st, monkeypatch):
    _two_gateways(monkeypatch)
    seen = []
    monkeypatch.setattr(bc, "reconcile_interrupted",
                        lambda store, host, policy, soc_getter=None, notify=None:
                        seen.append((host, soc_getter())) or [])
    for gid, host in (("gw-a", "10.0.0.1"), ("gw-b", "10.0.0.2")):
        st.record_dispatch(schedule_id=gid, name=gid, gateway_id=gid, host=host,
                           direction="charge", watts=50, power_mode="pct", target_soc=90,
                           window_start_ts=1, window_end_ts=time.time() + 600)
    bc.reconcile_all(st, "release")
    assert seen == [("10.0.0.1", 40), ("10.0.0.2", 80)]


def test_shutdown_releases_every_held_gateway(sent):
    bc._arm_watchdog("10.0.0.1", "Force Charge", 2000, 0, 0)
    bc._arm_watchdog("10.0.0.2", "Force Discharge", -1000, 0, 0)
    bc.release_held("shutdown")
    assert sorted(h for c, h in sent if c == "Release") == ["10.0.0.1", "10.0.0.2"]


# ── #193 ─────────────────────────────────────────────────────────────────────

def test_run_now_uses_the_schedules_gateway_not_the_viewed_one(st, sent, monkeypatch):
    monkeypatch.setattr(db, "get_store", lambda s: st)
    gws = {g.id: g for g in (_Gw("gw-a", "10.0.0.1", 40), _Gw("gw-b", "10.0.0.2", 80))}
    monkeypatch.setattr(app_module, "get_gateway", lambda gid: gws.get(gid))
    monkeypatch.setattr(state, "get_gateway", lambda gid: gws.get(gid))
    st.create_schedule(sid="b", name="on b", spec={"gateway_id": "gw-b", "fire_at": "14:00",
                                                  "duration_min": 60, "action": dict(FORCE)})
    TestClient(app_module.create_app()).post("/api/schedules/b/run?gateway=gw-a")
    assert [h for c, h in sent] == ["10.0.0.2"]


# ── #270 ─────────────────────────────────────────────────────────────────────

def test_scope_all_fires_once_on_each_gateway_per_occurrence(st, sent):
    st.create_schedule(sid="all", name="everywhere", spec={
        "gateway_scope": "all", "fire_at": "14:00", "duration_min": 60, "action": dict(FORCE)})
    for gid, host in (("gw-a", "10.0.0.1"), ("gw-b", "10.0.0.2")):
        sch.tick(settings=None, client=None, store=st, state={"soc": 50}, host=host,
                 gateway_id=gid, now=T0, modbus_host="")
    for gid, host in (("gw-a", "10.0.0.1"), ("gw-b", "10.0.0.2")):   # next tick: no repeat
        sch.tick(settings=None, client=None, store=st, state={"soc": 50}, host=host,
                 gateway_id=gid, now=T0 + dt.timedelta(seconds=15), modbus_host="")
    assert sent == [("Force Discharge", "10.0.0.1"), ("Force Discharge", "10.0.0.2")]
    fired = [e["gateway_id"] for e in st.schedule_log(schedule_id="all") if e["status"] == "fired"]
    assert sorted(fired) == ["gw-a", "gw-b"]
