"""#209 — an empty power is not a 0 W force, and a past window end is not a 1 s deadline."""
import time

from franklinwh_direct_connect_bridge import battery_control as bc
from franklinwh_direct_connect_bridge import resilience
from franklinwh_direct_connect_bridge import scheduler as sch


def test_empty_power_is_refused_not_sent_as_zero(monkeypatch):
    sent = []
    monkeypatch.setattr(bc, "execute", lambda cmd, **kw: (sent.append((cmd, kw)),
                                                         {"ok": True, "result": "ok"})[1])
    for power in (None, ""):
        out = sch._force_dispatch({"kind": "force", "direction": "charge", "unit": "w",
                                   "power": power}, host="h", window_min=30,
                                  gateway_id=None, store=None)
        assert "skipped" in out and "no power" in out
    assert sent == []
    # standby needs no power
    sch._force_dispatch({"kind": "force", "direction": "standby"}, host="h", window_min=30,
                        gateway_id=None, store=None)
    assert [c for c, _ in sent] == ["Force Standby"]


def test_a_window_end_already_past_keeps_the_policy_deadline(monkeypatch):
    seen = {}

    def _call(fn, **kw):
        seen["deadline_s"] = kw.get("deadline_s")
        return resilience.Outcome(verdict=resilience.Verdict.OK, action="force", target="h")
    monkeypatch.setattr(resilience, "call", _call)
    act = {"kind": "force", "direction": "charge", "unit": "w", "power": 1000}
    sch.run_action_outcome(act, settings=None, client=None, store=None, snapshot={},
                           host="h", window_end_ts=time.time() - 60)
    assert seen["deadline_s"] is None                       # not max(1.0, past) = 1 s
    sch.run_action_outcome(act, settings=None, client=None, store=None, snapshot={},
                           host="h", window_end_ts=time.time() + 600)
    assert 590 < seen["deadline_s"] <= 600                 # a future end still bounds it
