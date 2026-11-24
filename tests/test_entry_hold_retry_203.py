"""#203: a retry after a failed attempt must not wait the whole entry hold again.

The hold (entry_hold_s) is about the conditions staying true. Once it has been served, a
failed attempt is retried on the normal backoff while the conditions still hold; the hold
restarts only when the conditions stop holding.
"""
import datetime as dt

import pytest

from franklinwh_direct_connect_bridge import sched_monitor as mon
from franklinwh_direct_connect_bridge import scheduler as sch
from franklinwh_direct_connect_bridge.db import MetricsStore

NOON = dt.datetime(2026, 10, 28, 12, 5)
HOLD = 300


@pytest.fixture(autouse=True)
def _fresh():
    mon.clear()
    for d in (sch._window_inside, sch._window_key, sch._gated_day, sch._dwell_since):
        d.clear()
    yield
    mon.clear()


@pytest.fixture
def st(tmp_path, monkeypatch):
    s = MetricsStore(str(tmp_path / "m.db"))
    s.create_schedule(sid="h", name="held", spec={
        "gateway_id": "gw-a", "fire_at": "12:00", "duration_min": 60, "entry_hold_s": HOLD,
        "conditions": [{"sensor": "battery.soc_pct", "op": ">=", "value": 40}],
        "action": {"kind": "set_mode", "mode": "self"}})
    monkeypatch.setattr(sch, "_fire_ha_phase", lambda *a, **k: [])
    return s


def _tick(st, now, soc=50):
    return sch.tick(settings=None, client=None, store=st, state={"soc": soc}, host="h",
                    gateway_id="gw-a", now=now, modbus_host="")


def _fail_first(monkeypatch):
    calls = []

    def run(*a, **k):
        calls.append(1)
        return "mode -> self: failed — refused" if len(calls) == 1 else "mode -> self: ok"
    monkeypatch.setattr(sch, "run_action", run)
    return calls


def test_a_retry_fires_without_a_second_hold(st, monkeypatch):
    calls = _fail_first(monkeypatch)
    _tick(st, NOON)                                            # the hold starts
    _tick(st, NOON + dt.timedelta(seconds=HOLD))               # served: attempt 1 fails
    assert len(calls) == 1
    retry = NOON + dt.timedelta(seconds=HOLD + sch.RETRY_BASE_S)
    _tick(st, retry)                                           # backoff over: attempt 2
    assert len(calls) == 2, "the retry waited for the hold again"
    waiting = [r for r in st.schedule_log(limit=50)
               if r.get("schedule_id") == "h" and r.get("status") == "waiting"]
    assert len(waiting) == 1


def test_the_hold_restarts_when_the_conditions_stop_holding(st, monkeypatch):
    calls = _fail_first(monkeypatch)
    _tick(st, NOON)
    _tick(st, NOON + dt.timedelta(seconds=HOLD))               # attempt 1 fails
    _tick(st, NOON + dt.timedelta(seconds=HOLD + 15), soc=20)  # conditions break
    retry = NOON + dt.timedelta(seconds=HOLD + sch.RETRY_BASE_S)
    _tick(st, retry)
    assert len(calls) == 1, "a broken hold must be served again"
    _tick(st, retry + dt.timedelta(seconds=HOLD))
    assert len(calls) == 2
