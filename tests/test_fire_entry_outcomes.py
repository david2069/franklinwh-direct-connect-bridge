"""The defect that started this work: a failed action must not consume the occurrence."""
import datetime as dt
import types

from franklinwh_direct_connect_bridge import scheduler as SCH


class _Store:
    OCC_TERMINAL = ("ok", "missed", "skipped", "stopped", "unknown")

    def __init__(self):
        self.fired = []          # mark_schedule_fired calls
        self.events = []         # log_schedule_event calls
        self.finished = []       # finish_occurrence calls

    def mark_schedule_fired(self, sid, key, summary):
        self.fired.append((sid, key, summary))

    def log_schedule_event(self, sid, name, status, detail):
        self.events.append((status, detail))

    def finish_occurrence(self, occ_id, *, status, outcome="", reason=""):
        self.finished.append((occ_id, status))


def _fire(monkeypatch, result: str, occ_id=7):
    store = _Store()
    monkeypatch.setattr(SCH, "run_action", lambda *a, **k: result)
    monkeypatch.setattr(SCH, "_fire_ha_phase", lambda *a, **k: [])
    entry = {"id": "s1", "name": "nightly", "action": {"kind": "set_mode"},
             "_wkey": "2026-10-09", "_wend": None, "_occ_id": occ_id,
             "_occ_attempts": 1, "duration_min": 60}
    out = SCH._fire_entry(entry, settings=None, client=None, store=store,
                          snapshot={}, host="h", gateway_id="gw1",
                          now=dt.datetime(2026, 10, 9, 18, 0))
    return store, out


def test_success_marks_fired_and_closes_the_run(monkeypatch):
    store, out = _fire(monkeypatch, "mode -> self: ok")
    assert out["ok"] is True
    assert len(store.fired) == 1, "a successful run consumes its occurrence"
    assert store.finished == [(7, "ok")]
    assert store.events[0][0] == "fired"


def test_a_failed_action_does_NOT_mark_fired(monkeypatch):
    # The whole defect: mark_schedule_fired used to run unconditionally, and due()
    # then refused to re-enter — so a two-second blip burned the occurrence silently.
    store, out = _fire(monkeypatch, "force charge: failed — connection refused")
    assert out["ok"] is False
    assert store.fired == [], "a failure must leave the occurrence re-enterable"
    assert store.finished == [(7, "failed")]


def test_a_failure_is_logged_with_the_retry_interval(monkeypatch):
    store, _ = _fire(monkeypatch, "force charge: failed — timeout")
    status, detail = store.events[0]
    assert status == "error"
    assert "attempt 1" in detail and "retrying in" in detail, (
        "the operator should not have to infer that a retry is coming")


def test_an_unconfirmed_write_counts_as_failure(monkeypatch):
    store, out = _fire(monkeypatch, "mode -> tou: NOT confirmed")
    assert out["ok"] is False and store.fired == []
