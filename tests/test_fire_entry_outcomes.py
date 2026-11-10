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

    def log_schedule_event(self, sid, name, status, detail, gateway_id=""):
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


# ── phase 3: the scheduler decides on the VERDICT, not on the words ──────────
def test_an_unknown_write_is_never_retried_and_settles_the_run(monkeypatch):
    """A write that timed out AFTER the request left may have landed. Retrying it
    is how you dispatch twice, so UNKNOWN closes the occurrence instead."""
    from franklinwh_direct_connect_bridge import resilience as R
    store = _Store()
    monkeypatch.setattr(SCH, "run_action_outcome", lambda *a, **k: R.Outcome(
        verdict=R.Verdict.UNKNOWN, action="force", detail="force: no reply after send"))
    monkeypatch.setattr(SCH, "_fire_ha_phase", lambda *a, **k: [])
    entry = {"id": "s1", "name": "nightly", "action": {"kind": "force"},
             "_wkey": "2026-10-12", "_wend": None, "_occ_id": 9,
             "_occ_attempts": 1, "duration_min": 60}
    out = SCH._fire_entry(entry, settings=None, client=None, store=store, snapshot={},
                          host="h", gateway_id="gw1", now=dt.datetime(2026, 10, 12, 18, 0))
    assert out["ok"] is False and out["unknown"] is True
    assert (9, "unknown") in store.finished, "the run is settled, not left to retry"
    assert any(st == "unknown" for st, _ in store.events)


def test_a_skipped_action_is_not_a_failure(monkeypatch):
    """Preconditions unmet means nothing was attempted. Treating that as a failure
    would retry a rule that was never going to run."""
    from franklinwh_direct_connect_bridge import resilience as R
    store = _Store()
    monkeypatch.setattr(SCH, "run_action_outcome", lambda *a, **k: R.Outcome(
        verdict=R.Verdict.SKIPPED, action="reserve_soc",
        detail="reserve_soc skipped: no local write path exists"))
    monkeypatch.setattr(SCH, "_fire_ha_phase", lambda *a, **k: [])
    entry = {"id": "s1", "name": "n", "action": {"kind": "reserve_soc"},
             "_wkey": "2026-10-12", "_wend": None, "_occ_id": 3,
             "_occ_attempts": 1, "duration_min": 0}
    out = SCH._fire_entry(entry, settings=None, client=None, store=store, snapshot={},
                          host="h", gateway_id="gw1", now=dt.datetime(2026, 10, 12, 18, 0))
    assert out["ok"] is True and out.get("unknown") is not True


def test_failure_text_that_lacks_the_word_failed_is_still_a_failure(monkeypatch):
    """The old test was `"failed" not in result`, so any failure phrased without
    that word was recorded as a success."""
    from franklinwh_direct_connect_bridge import resilience as R
    store = _Store()
    monkeypatch.setattr(SCH, "run_action_outcome", lambda *a, **k: R.Outcome(
        verdict=R.Verdict.FAILED, action="set_mode", detail="the aGate refused it"))
    monkeypatch.setattr(SCH, "_fire_ha_phase", lambda *a, **k: [])
    entry = {"id": "s1", "name": "n", "action": {"kind": "set_mode"},
             "_wkey": "2026-10-12", "_wend": None, "_occ_id": 4,
             "_occ_attempts": 1, "duration_min": 0}
    out = SCH._fire_entry(entry, settings=None, client=None, store=store, snapshot={},
                          host="h", gateway_id="gw1", now=dt.datetime(2026, 10, 12, 18, 0))
    assert out["ok"] is False and store.fired == []


def test_a_write_reporting_failure_text_is_classified_as_failed(monkeypatch):
    """run_action never raises — it returns a failure STRING — so the Outcome path
    has to read the text as well, or resilience sees a clean return."""
    from franklinwh_direct_connect_bridge import resilience as R
    monkeypatch.setattr(SCH, "run_action", lambda *a, **k: "mode -> tou: failed")
    out = SCH.run_action_outcome({"kind": "set_mode", "mode": "tou"}, settings=None,
                                 client=None, store=None, snapshot={}, host="h",
                                 gateway_id="gw1")
    assert out.verdict is R.Verdict.FAILED


def test_a_refused_action_reads_as_skipped_not_ok(monkeypatch):
    from franklinwh_direct_connect_bridge import resilience as R
    out = SCH.run_action_outcome({"kind": "reserve_soc"}, settings=None, client=None,
                                 store=None, snapshot={}, host="h", gateway_id="gw1")
    assert out.verdict is R.Verdict.SKIPPED
