"""#204: If busy = defer settles the occurrence it lost, once. An interval rule ticked
again inside the same slot while the battery is still busy is not deferred and logged on
every tick."""
import datetime as dt

from franklinwh_direct_connect_bridge import battery_control as bc
from franklinwh_direct_connect_bridge import scheduler as sch
from franklinwh_direct_connect_bridge.db import MetricsStore


def test_an_interval_rule_defers_once_per_slot(tmp_path, monkeypatch):
    ran = []
    monkeypatch.setattr(bc, "execute", lambda cmd, **kw: (ran.append(cmd), {
        "ok": True, "result": "ok", "active": cmd})[1])
    monkeypatch.setattr(bc, "current", lambda host=None: {"active": "Not Active"})
    st = MetricsStore(str(tmp_path / "m.db"))
    st.record_dispatch(schedule_id="A", name="A", gateway_id=None, host="h",
                       direction="discharge", watts=-2000, power_mode="w", target_soc=0,
                       window_start_ts=1, window_end_ts=9e18)
    st.create_schedule(sid="B", name="B every 30", spec={
        "gateway_id": "gw-h", "trigger_type": "interval", "interval_min": 30,
        "duration_min": 20, "enabled": True, "conflict": "defer",
        "action": {"kind": "force", "direction": "discharge", "unit": "pct", "power": 50}})
    for d in (sch._window_inside, sch._window_key, sch._gated_day, sch._dwell_since):
        d.clear()
    for minute in (1, 2, 3, 10):            # all inside the 14:00 slot
        sch.tick(settings=None, client=None, store=st, state={"soc": 50}, host="h",
                 gateway_id="gw-h", now=dt.datetime(2026, 9, 22, 14, minute))
    deferred = [e for e in st.schedule_log(schedule_id="B") if e["status"] == "deferred"]
    assert ran == [] and len(deferred) == 1, [e["result"] for e in deferred]
    # The next slot is a new occurrence: it is considered (and deferred) again.
    sch.tick(settings=None, client=None, store=st, state={"soc": 50}, host="h",
             gateway_id="gw-h", now=dt.datetime(2026, 9, 22, 14, 31))
    assert len([e for e in st.schedule_log(schedule_id="B") if e["status"] == "deferred"]) == 2


def _busy_store(tmp_path, monkeypatch, spec):
    monkeypatch.setattr(bc, "execute", lambda cmd, **kw: {"ok": True, "result": "ok", "active": cmd})
    monkeypatch.setattr(bc, "current", lambda host=None: {"active": "Not Active"})
    st = MetricsStore(str(tmp_path / "m.db"))
    st.record_dispatch(schedule_id="A", name="A", gateway_id=None, host="h",
                       direction="discharge", watts=-2000, power_mode="w", target_soc=0,
                       window_start_ts=1, window_end_ts=9e18)
    st.create_schedule(sid="B", name="B", spec={"gateway_id": "gw-h", "enabled": True,
        "conflict": "defer",
        "action": {"kind": "force", "direction": "discharge", "unit": "pct", "power": 50},
        **spec})
    for d in (sch._window_inside, sch._window_key, sch._gated_day, sch._dwell_since):
        d.clear()
    return st


def _deferred(st):
    return len([e for e in st.schedule_log(schedule_id="B") if e["status"] == "deferred"])


def test_a_cron_rule_defers_once_per_slot(tmp_path, monkeypatch):
    st = _busy_store(tmp_path, monkeypatch, {"trigger_type": "cron", "cron": "0 * * * *",
                                              "duration_min": 20})
    for minute in (1, 2, 5):
        sch.tick(settings=None, client=None, store=st, state={"soc": 50}, host="h",
                 gateway_id="gw-h", now=dt.datetime(2026, 9, 22, 14, minute))
    assert _deferred(st) == 1


def test_a_second_window_defers_once_and_the_first_doesnt_stop_it(tmp_path, monkeypatch):
    st = _busy_store(tmp_path, monkeypatch, {"trigger_type": "window", "windows": [
        {"start": "09:00", "end": "10:00"}, {"start": "14:00", "end": "15:00"}]})
    for h, m in ((9, 5), (9, 6), (14, 5), (14, 6)):
        sch.tick(settings=None, client=None, store=st, state={"soc": 50}, host="h",
                 gateway_id="gw-h", now=dt.datetime(2026, 9, 22, h, m))
    assert _deferred(st) == 2
