"""Connectivity history — RUNTIME_DESIGN §6.9 (phase 2b).

The questions this exists to answer could not be answered before, and not because no
screen showed them: when did this gateway first connect, how long has the current
outage run, how many retries did the last one take. Nothing wrote them down, so every
outage was unrecoverable the moment it ended.
"""
import pytest

from franklinwh_direct_connect_bridge import db as db_mod


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("METRICS_DB", str(tmp_path / "t.db"))
    return db_mod.MetricsStore(str(tmp_path / "t.db"))


T0 = 1_000_000.0


# ── the debounce: a transition is not a sample ───────────────────────────────
def test_one_failed_probe_is_not_an_outage(store):
    """The false positive that prompted this: a single timed-out login flipped the UI
    to Offline while Modbus was up and the data was fresh."""
    store.record_link_probe("gw1", "ok", now=T0)
    r = store.record_link_probe("gw1", "failed", error="refused", now=T0 + 30)
    assert r["state"] == "up" and r["transition"] is None
    assert store.link_outages("gw1") == []


def test_the_link_is_declared_down_only_after_the_strikes(store):
    store.record_link_probe("gw1", "ok", now=T0)
    seen = [store.record_link_probe("gw1", "failed", now=T0 + 30 * i)["state"]
            for i in range(1, store.LINK_STRIKES + 1)]
    assert seen[-1] == "down" and seen[:-1] == ["up"] * (store.LINK_STRIKES - 1)


def test_one_success_clears_it(store):
    store.record_link_probe("gw1", "ok", now=T0)
    for i in range(1, store.LINK_STRIKES + 1):
        store.record_link_probe("gw1", "failed", now=T0 + 30 * i)
    r = store.record_link_probe("gw1", "ok", now=T0 + 300)
    assert r["state"] == "up" and r["transition"] == "up"


def test_the_transition_is_reported_once_not_every_tick(store):
    """Callers notify on the transition and nothing else; reporting the state each
    cycle is the alert-spam failure this design exists to prevent."""
    store.record_link_probe("gw1", "ok", now=T0)
    trans = [store.record_link_probe("gw1", "failed", now=T0 + 30 * i)["transition"]
             for i in range(1, 10)]
    assert trans.count("down") == 1


# ── the history itself ───────────────────────────────────────────────────────
def test_an_outage_is_dated_from_the_first_failure(store):
    """Dating it from the strike that CONFIRMED it under-reports every outage by
    (strikes - 1) poll intervals."""
    store.record_link_probe("gw1", "ok", now=T0)
    for i in range(1, 4):
        store.record_link_probe("gw1", "failed", now=T0 + 30 * i)   # first failure at +30
    r = store.record_link_probe("gw1", "ok", now=T0 + 150)
    assert r["outage_s"] == pytest.approx(120.0)
    assert store.link_outages("gw1")[0]["duration_s"] == pytest.approx(120.0)


def test_retries_during_the_outage_are_counted(store):
    store.record_link_probe("gw1", "ok", now=T0)
    for i in range(1, 9):
        store.record_link_probe("gw1", "failed", error="refused", now=T0 + 30 * i)
    o = store.link_outages("gw1")[0]
    assert o["attempts"] == 8 and o["last_error"] == "refused"


def test_first_and_last_connection_are_remembered(store):
    store.record_link_probe("gw1", "ok", now=T0)
    store.record_link_probe("gw1", "failed", now=T0 + 30)
    store.record_link_probe("gw1", "ok", now=T0 + 60)
    st = store.link_state("gw1")
    assert st["first_ok_ts"] == T0 and st["last_ok_ts"] == T0 + 60


def test_a_failure_does_not_move_the_last_good_timestamp(store):
    """'How stale is what I am looking at' is measured from the last SUCCESS."""
    store.record_link_probe("gw1", "ok", now=T0)
    store.record_link_probe("gw1", "failed", now=T0 + 600)
    assert store.link_state("gw1")["last_ok_ts"] == T0


# ── a timeout is not a refusal ───────────────────────────────────────────────
def test_unknown_counts_toward_the_strikes_but_is_tallied_apart(store):
    """Not knowing is not evidence of health — but a link that times out must still be
    tellable from one that is actively refusing."""
    store.record_link_probe("gw1", "ok", now=T0)
    for i in range(1, store.LINK_STRIKES + 1):
        r = store.record_link_probe("gw1", "unknown", error="timed out", now=T0 + 30 * i)
    assert r["state"] == "down"
    st = store.link_state("gw1")
    assert st["unknowns"] == store.LINK_STRIKES and st["failures"] == store.LINK_STRIKES


def test_an_unrecognised_outcome_is_not_treated_as_success(store):
    store.record_link_probe("gw1", "nonsense", now=T0)
    assert store.link_state("gw1")["last_outcome"] == "failed"


# ── missed polls ─────────────────────────────────────────────────────────────
def test_cycles_that_never_ran_are_counted_from_the_gap(store):
    """The cycles that go missing are precisely the ones that never ran to report
    themselves, so they are counted from the gap, not from a tick."""
    store.record_link_probe("gw1", "ok", expected_interval_s=30, now=T0)
    store.record_link_probe("gw1", "ok", expected_interval_s=30, now=T0 + 300)
    assert store.link_state("gw1")["missed_polls"] == 9


def test_a_poll_on_cadence_misses_nothing(store):
    store.record_link_probe("gw1", "ok", expected_interval_s=30, now=T0)
    store.record_link_probe("gw1", "ok", expected_interval_s=30, now=T0 + 30)
    assert store.link_state("gw1")["missed_polls"] == 0


# ── retention ────────────────────────────────────────────────────────────────
def test_closed_outages_age_out_by_time(store):
    store.record_link_probe("gw1", "ok", now=T0)
    for i in range(1, 4):
        store.record_link_probe("gw1", "failed", now=T0 + 30 * i)
    store.record_link_probe("gw1", "ok", now=T0 + 150)
    assert store.prune_link_outages(days=1, now=T0 + 10 * 86400) == 1


def test_a_running_outage_is_never_pruned(store):
    """It is the live answer to 'how long has this been down'."""
    store.record_link_probe("gw1", "ok", now=T0)
    for i in range(1, 4):
        store.record_link_probe("gw1", "failed", now=T0 + 30 * i)
    assert store.prune_link_outages(days=1, now=T0 + 10 * 86400) == 0
    assert len(store.link_outages("gw1", open_only=True)) == 1


def test_gateways_are_tracked_independently(store):
    store.record_link_probe("gw1", "ok", now=T0)
    for i in range(1, 4):
        store.record_link_probe("gw2", "failed", now=T0 + 30 * i)
    assert store.link_state("gw1")["state"] == "up"
    assert store.link_state("gw2")["state"] == "down"


def test_a_gateway_never_probed_has_no_state(store):
    assert store.link_state("never") is None


# ── a leg that has never connected ───────────────────────────────────────────
def test_a_leg_that_never_succeeded_is_unknown_not_up(store):
    """Holding the previous verdict through the debounce is right for a link that WAS
    up. A link with no previous verdict has nothing to hold, and reporting `up` would
    assert something never observed."""
    r = store.record_link_probe("gw1", "failed", leg="modbus_502", error="closed", now=T0)
    assert r["state"] == "unknown"


def test_it_still_reaches_down_once_the_strikes_are_met(store):
    for i in range(store.LINK_STRIKES):
        r = store.record_link_probe("gw1", "failed", leg="modbus_502", now=T0 + 30 * i)
    assert r["state"] == "down"


def test_a_link_that_was_up_holds_its_verdict_through_the_debounce(store):
    store.record_link_probe("gw1", "ok", leg="modbus_502", now=T0)
    r = store.record_link_probe("gw1", "failed", leg="modbus_502", now=T0 + 30)
    assert r["state"] == "up", "one failure does not unseat a link known to work"


# ── legs are independent ─────────────────────────────────────────────────────
def test_one_leg_failing_does_not_affect_another(store):
    """A closed Modbus port must not hide behind a healthy :9000, nor vice versa."""
    store.record_link_probe("gw1", "ok", leg="local_9000", now=T0)
    for i in range(1, store.LINK_STRIKES + 1):
        store.record_link_probe("gw1", "failed", leg="modbus_502", now=T0 + 30 * i)
    by = {r["leg"]: r["state"] for r in store.link_states("gw1")}
    assert by["local_9000"] == "up" and by["modbus_502"] == "down"


def test_every_recorded_leg_is_named_in_plain_words(store):
    store.record_link_probe("gw1", "ok", leg="icmp", now=T0)
    assert store.link_state("gw1", "icmp")["label"] == store.LINK_LEGS["icmp"]


def test_legs_are_returned_in_catalogue_order(store):
    """Stable display order, not whichever leg happened to be probed first."""
    store.record_link_probe("gw1", "ok", leg="icmp", now=T0)
    store.record_link_probe("gw1", "ok", leg="local_9000", now=T0)
    assert [r["leg"] for r in store.link_states("gw1")] == ["local_9000", "icmp"]
