"""The execution queue — recording what is EXPECTED so absence becomes detectable.

Until this table existed, a run that never happened left no trace: an outage, a failed
action and a rule nobody enabled were indistinguishable, because the only evidence of a
run was the log line written after it succeeded.
"""
import time

import pytest

from franklinwh_direct_connect_bridge import db as db_mod


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("METRICS_DB", str(tmp_path / "t.db"))
    s = db_mod.MetricsStore(str(tmp_path / "t.db"))
    yield s


def _claim(store, *, sid="s1", key="2026-10-09", gw="gw1", due=None, end=None, now=None):
    now = now or time.time()
    return store.claim_occurrence(
        schedule_id=sid, name="nightly", gateway_id=gw, occurrence_key=key,
        due_ts=due if due is not None else now,
        window_end_ts=end if end is not None else now + 3600, now=now)


# ── claiming (max_instances, in the schema) ───────────────────────────────────
def test_claiming_registers_a_pending_run(store):
    occ = _claim(store)
    assert occ["status"] == "pending" and occ["attempts"] == 0


def test_claiming_twice_returns_the_same_run(store):
    a, b = _claim(store), _claim(store)
    assert a["id"] == b["id"], "one run per occurrence — enforced in the schema"


def test_the_same_rule_on_two_gateways_is_two_runs(store):
    a = _claim(store, gw="gw1")
    b = _claim(store, gw="gw2")
    assert a["id"] != b["id"]


def test_a_finished_run_is_visible_to_the_next_claim(store):
    occ = _claim(store)
    store.finish_occurrence(occ["id"], status="ok")
    assert _claim(store)["status"] == "ok", "so a caller can leave it alone"


# ── attempts and outcomes ─────────────────────────────────────────────────────
def test_attempts_accumulate_so_thrashing_is_visible(store):
    occ = _claim(store)
    for _ in range(3):
        store.occurrence_attempt(occ["id"])
    assert _claim(store)["attempts"] == 3


def test_finishing_records_the_reason(store):
    occ = _claim(store)
    store.finish_occurrence(occ["id"], status="skipped", reason="modbus unreachable")
    row = _claim(store)
    assert row["status"] == "skipped" and "modbus" in row["reason"]


def test_reopening_retries_without_erasing_the_attempt_history(store):
    occ = _claim(store)
    store.occurrence_attempt(occ["id"])
    store.finish_occurrence(occ["id"], status="failed", reason="timeout")
    store.reopen_occurrence(occ["id"])
    row = _claim(store)
    assert row["status"] == "pending"
    assert row["attempts"] == 1, "the evidence of how hard this was tried must survive"


# ── the missed sweep: the whole point ─────────────────────────────────────────
def test_a_run_whose_window_closed_while_pending_is_missed(store):
    now = time.time()
    _claim(store, due=now - 7200, end=now - 3600, now=now - 7200)
    missed = store.sweep_missed(now=now)
    assert len(missed) == 1
    row = _claim(store, due=now - 7200, end=now - 3600)
    assert row["status"] == "missed" and "no success" in row["reason"]


def test_an_open_window_is_not_missed(store):
    now = time.time()
    _claim(store, due=now - 60, end=now + 3600, now=now)
    assert store.sweep_missed(now=now) == []


def test_grace_lets_a_late_run_still_catch_up(store):
    now = time.time()
    _claim(store, due=now - 300, end=now - 30, now=now - 300)
    assert store.sweep_missed(grace_s=120, now=now) == [], "30s late, 120s grace"
    assert len(store.sweep_missed(grace_s=10, now=now)) == 1


def test_a_succeeded_run_is_never_swept(store):
    now = time.time()
    occ = _claim(store, due=now - 7200, end=now - 3600, now=now - 7200)
    store.finish_occurrence(occ["id"], status="ok")
    assert store.sweep_missed(now=now) == []


# ── Stop vs Pause vs Resume (owner decision, 2026-10-09) ──────────────────────
def test_stop_ends_the_occurrence(store):
    occ = _claim(store)
    store.finish_occurrence(occ["id"], status="stopped", reason="stopped by user")
    assert _claim(store)["status"] == "stopped"
    assert "stopped" in db_mod.MetricsStore.OCC_TERMINAL


def test_pause_keeps_the_occurrence(store):
    occ = _claim(store)
    store.pause_occurrence(occ["id"])
    row = _claim(store)
    assert row["status"] == "paused"
    assert "paused" not in db_mod.MetricsStore.OCC_TERMINAL, "Pause holds your place"


def test_resume_re_enters_while_the_window_is_open(store):
    now = time.time()
    occ = _claim(store, due=now - 60, end=now + 600, now=now)
    store.pause_occurrence(occ["id"], now=now)
    ok, why = store.resume_occurrence(occ["id"], now=now)
    assert ok and why == ""
    assert _claim(store, due=now - 60, end=now + 600)["status"] == "pending"


def test_resume_refuses_once_the_window_has_closed(store):
    now = time.time()
    occ = _claim(store, due=now - 7200, end=now - 60, now=now - 7200)
    store.pause_occurrence(occ["id"], now=now - 3600)
    ok, why = store.resume_occurrence(occ["id"], now=now)
    assert not ok and "window has closed" in why, (
        "a resume that silently did nothing is worse than an error")


def test_resume_refuses_what_was_never_paused(store):
    occ = _claim(store)
    ok, why = store.resume_occurrence(occ["id"])
    assert not ok and "not paused" in why


def test_a_restart_while_paused_resolves_to_terminal(store):
    occ = _claim(store)
    store.pause_occurrence(occ["id"])
    resolved = store.resolve_paused_on_boot()
    assert len(resolved) == 1
    row = _claim(store)
    assert row["status"] == "stopped" and "restarted" in row["reason"], (
        "nobody is holding the place once the process is gone")


def test_pause_is_not_swept_as_missed(store):
    now = time.time()
    occ = _claim(store, due=now - 7200, end=now - 3600, now=now - 7200)
    store.pause_occurrence(occ["id"], now=now - 7000)
    assert store.sweep_missed(now=now) == [], "a decision is not a failure"


# ── the dashboard ─────────────────────────────────────────────────────────────
def test_stats_answer_runs_first_last_and_last_failure(store):
    now = time.time()
    for i, st in enumerate(("ok", "ok", "failed", "missed")):
        occ = _claim(store, key=f"d{i}", due=now - (10 - i) * 3600, end=now + 3600,
                     now=now - (10 - i) * 3600)
        store.finish_occurrence(occ["id"], status=st)
    s = store.occurrence_stats("s1")[0]
    assert s["runs"] == 4 and s["ok"] == 2 and s["missed"] == 1 and s["failed"] == 1
    assert s["first_ts"] < s["last_ts"]
    assert s["last_failure_ts"] is not None


def test_due_returns_only_open_claimable_work(store):
    now = time.time()
    _claim(store, key="open", due=now - 60, end=now + 600, now=now)
    _claim(store, key="future", due=now + 600, end=now + 1200, now=now)
    done = _claim(store, key="done", due=now - 60, end=now + 600, now=now)
    store.finish_occurrence(done["id"], status="ok")
    assert [o["occurrence_key"] for o in store.due_occurrences(now=now)] == ["open"]


# ── retention: time-based, so noise cannot evict history ──────────────────────
def test_pruning_is_by_age_and_spares_live_work(store):
    now = time.time()
    old = _claim(store, key="old", due=now - 200 * 86400, end=now - 200 * 86400 + 60,
                 now=now - 200 * 86400)
    store.finish_occurrence(old["id"], status="ok")
    _claim(store, key="live", due=now - 60, end=now + 600, now=now)
    assert store.prune_occurrences(keep_days=90, now=now) == 1
    assert [o["occurrence_key"] for o in store.due_occurrences(now=now)] == ["live"]


# ── retry backoff (scheduler-side) ────────────────────────────────────────────
from franklinwh_direct_connect_bridge import scheduler as SCH  # noqa: E402


def test_backoff_grows_and_is_capped():
    assert SCH.retry_delay_s(0) == 0.0
    assert SCH.retry_delay_s(1) == SCH.RETRY_BASE_S
    assert SCH.retry_delay_s(2) == SCH.RETRY_BASE_S * 2
    assert SCH.retry_delay_s(99) == SCH.RETRY_CAP_S


def test_a_window_of_ticks_does_not_become_a_window_of_attempts():
    # The scheduler ticks every 15s. Without backoff a rule failing against an
    # unreachable gateway would attempt ~360 times in a 90-minute window and bury the
    # history in noise.
    window_s, tick_s = 90 * 60, 15
    t, attempts, elapsed = 0.0, 0, 0.0
    while elapsed < window_s:
        if SCH.retry_due({"attempts": attempts, "last_attempt_ts": t}, elapsed):
            attempts += 1
            t = elapsed
        elapsed += tick_s
    assert attempts < 15, f"{attempts} attempts in 90 minutes is still too hot"
    assert attempts >= 5, "but it must keep trying while the window is open"


def test_a_never_attempted_run_is_due_immediately():
    assert SCH.retry_due({"attempts": 0, "last_attempt_ts": None}, 1000.0)


def test_backoff_blocks_the_very_next_tick_after_a_failure():
    occ = {"attempts": 1, "last_attempt_ts": 1000.0}
    assert not SCH.retry_due(occ, 1015.0), "15s later — still backing off"
    assert SCH.retry_due(occ, 1000.0 + SCH.RETRY_BASE_S)


# ── end-to-end against a REAL store: claim -> attempt -> finish ───────────────
def test_the_full_path_records_a_run_against_real_sql(store, monkeypatch):
    """Drives _claim_run + occurrence_attempt + _fire_entry against actual SQLite,
    rather than a stand-in, so the schema and the code agree."""
    import datetime as dt
    now = dt.datetime(2026, 10, 9, 18, 0)
    entry = {"id": "s-e2e", "name": "evening export", "action": {"kind": "set_mode"},
             "_wkey": "2026-10-09", "_wend": now.timestamp() + 3600, "duration_min": 60}

    occ = SCH._claim_run(entry, store=store, gateway_id="gw1", now=now)
    assert occ is not None and occ["status"] == "pending"
    store.occurrence_attempt(occ["id"], now=now.timestamp())
    entry["_occ_id"], entry["_occ_attempts"] = occ["id"], 1

    monkeypatch.setattr(SCH, "run_action", lambda *a, **k: "mode -> self: ok")
    monkeypatch.setattr(SCH, "_fire_ha_phase", lambda *a, **k: [])
    out = SCH._fire_entry(entry, settings=None, client=None, store=store,
                          snapshot={}, host="h", gateway_id="gw1", now=now)

    assert out["ok"] is True
    row = store.occurrences_for("s-e2e")[0]
    assert row["status"] == "ok" and row["attempts"] == 1
    assert row["outcome"] and row["started_ts"] and row["ended_ts"]


def test_a_failure_leaves_the_run_retryable_against_real_sql(store, monkeypatch):
    import datetime as dt
    now = dt.datetime(2026, 10, 9, 18, 0)
    entry = {"id": "s-fail", "name": "evening export", "action": {"kind": "force"},
             "_wkey": "2026-10-09", "_wend": now.timestamp() + 3600, "duration_min": 60}
    occ = SCH._claim_run(entry, store=store, gateway_id="gw1", now=now)
    store.occurrence_attempt(occ["id"], now=now.timestamp())
    entry["_occ_id"], entry["_occ_attempts"] = occ["id"], 1

    monkeypatch.setattr(SCH, "run_action", lambda *a, **k: "force: failed — refused")
    monkeypatch.setattr(SCH, "_fire_ha_phase", lambda *a, **k: [])
    SCH._fire_entry(entry, settings=None, client=None, store=store, snapshot={},
                    host="h", gateway_id="gw1", now=now)

    row = store.occurrences_for("s-fail")[0]
    assert row["status"] == "failed", "still claimable — the window is open"
    assert row["id"] in [o["id"] for o in store.due_occurrences(now=now.timestamp())]


def test_claiming_survives_a_broken_store(monkeypatch):
    """A bookkeeping fault must not become an outage."""
    import datetime as dt

    class Broken:
        def claim_occurrence(self, **kw):
            raise RuntimeError("disk full")

    assert SCH._claim_run({"id": "x", "name": "n", "_wkey": "k", "_wend": None},
                          store=Broken(), gateway_id="gw1",
                          now=dt.datetime(2026, 10, 9, 18, 0)) is None
