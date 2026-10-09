"""Phase 1 — the scheduler as its own component.

The behaviour most worth protecting is the one DECOUPLING introduced. While the
scheduler ran inside the poll loop it could only evaluate just-read data. On its own
cadence it can outlive a poller, so it must refuse to decide anything from a snapshot
that stopped being updated — a schedule firing on a three-hour-old SoC is a worse
failure than one that does not fire.
"""
import time
import types

import pytest

from franklinwh_direct_connect_bridge import scheduler_worker as SW
from franklinwh_direct_connect_bridge.config import Settings


def _gw(gid="gw1", *, age_s=0.0, enabled=True, state=None, mock=False):
    return types.SimpleNamespace(
        id=gid, enabled=enabled, is_mock=mock,
        last_state=state if state is not None else {"soc": 50},
        state_ts=(time.time() - age_s) if age_s is not None else 0.0,
        active_host="10.0.0.5", configured_host="10.0.0.5")


def _settings(**kw):
    return Settings(**kw) if kw else Settings()


# ── cadence is explicit, not inherited (decision 2) ───────────────────────────
def test_cadence_has_its_own_setting_and_does_not_follow_poll_interval():
    s = _settings()
    assert s.scheduler_tick_s == 15
    assert s.scheduler_tick_s != s.poll_interval, (
        "the whole point of phase 1 is that scheduling resolution is not an accident "
        "of how often the gateway happens to be read")


# ── freshness (the hazard decoupling creates) ─────────────────────────────────
def test_a_fresh_gateway_is_eligible():
    ok, why = SW.eligible(_gw(age_s=5), _settings())
    assert ok and why == ""


def test_a_stale_snapshot_is_skipped_with_a_reason():
    ok, why = SW.eligible(_gw(age_s=10_000), _settings())
    assert not ok
    assert "old" in why and "not evaluating" in why


def test_a_gateway_that_never_polled_is_not_treated_as_fresh():
    gw = _gw()
    gw.state_ts = 0.0
    ok, why = SW.eligible(gw, _settings())
    assert not ok and "no state snapshot" in why
    assert SW.snapshot_age_s(gw) == float("inf"), (
        "absence of data is not evidence of health")


def test_a_disabled_gateway_is_skipped():
    ok, why = SW.eligible(_gw(enabled=False), _settings())
    assert not ok and "disabled" in why


def test_the_staleness_limit_follows_poll_interval_with_a_floor():
    assert SW.staleness_limit_s(_settings(poll_interval=5)) == 90.0     # floored
    assert SW.staleness_limit_s(_settings(poll_interval=60)) == 180.0   # 3 intervals


@pytest.mark.parametrize("age,expected", [(10, True), (89, True), (91, False)])
def test_the_boundary_is_where_it_says_it_is(age, expected):
    ok, _ = SW.eligible(_gw(age_s=age), _settings(poll_interval=30))
    assert ok is expected


# ── per-gateway context ───────────────────────────────────────────────────────
def test_mock_gateways_skip_the_modbus_read():
    assert SW._context(_gw(mock=True))["modbus_host"] == ""
    assert SW._context(_gw(mock=False))["modbus_host"] == "10.0.0.5"


def test_context_carries_the_snapshot_the_poller_wrote():
    gw = _gw(state={"soc": 42})
    assert SW._context(gw)["state"] == {"soc": 42}
    assert SW._context(gw)["gateway_id"] == gw.id


# ── one gateway's failure must not stop the others ────────────────────────────
def test_a_failing_gateway_does_not_stop_the_rest(monkeypatch):
    gws = [_gw("bad"), _gw("good")]
    monkeypatch.setattr(SW, "get_gateways", lambda: gws)
    monkeypatch.setattr(SW, "get_store", lambda s: object())

    def fake_tick(*, settings, client, store, state, host, modbus_host, gateway_id):
        if gateway_id == "bad":
            raise RuntimeError("gateway exploded")
        return [{"id": "s1", "name": "nightly", "result": "fired"}]

    monkeypatch.setattr(SW._sched, "tick", fake_tick)
    fired = SW.tick_once(_settings(), client=None)
    assert [f["gateway_id"] for f in fired] == ["good"], (
        "the coupled version let one gateway stop all scheduling; this must not")


def test_stale_gateways_are_not_passed_to_tick_at_all(monkeypatch):
    calls = []
    monkeypatch.setattr(SW, "get_gateways", lambda: [_gw("stale", age_s=10_000)])
    monkeypatch.setattr(SW, "get_store", lambda s: object())
    monkeypatch.setattr(SW._sched, "tick", lambda **kw: calls.append(kw) or [])
    assert SW.tick_once(_settings(), client=None) == []
    assert calls == [], "a stale snapshot must never reach the evaluator"


def test_no_store_means_no_scheduling_rather_than_a_crash(monkeypatch):
    monkeypatch.setattr(SW, "get_store", lambda s: None)
    assert SW.tick_once(_settings(), client=None) == []


# ── the cadence guarantee (decision 2, refined) ───────────────────────────────
def test_cadence_is_clamped_so_no_expressible_window_can_be_missed():
    assert SW.cadence_for(_settings(scheduler_tick_s=15)) == 15
    assert SW.cadence_for(_settings(scheduler_tick_s=600)) == SW.MAX_TICK_S
    assert SW.cadence_for(_settings(scheduler_tick_s=1)) == SW.MIN_TICK_S


def test_zero_means_unset_and_takes_the_default_not_the_floor():
    # 0 is "not configured", which is different from "configured absurdly low".
    assert SW.cadence_for(_settings(scheduler_tick_s=0)) == 15


def test_a_misconfigured_cadence_is_corrected_loudly(caplog):
    with caplog.at_level("WARNING"):
        SW.cadence_for(_settings(scheduler_tick_s=300))
    assert "clamped" in caplog.text and "never fire" in caplog.text, (
        "a silently-never-firing schedule is the exact class this work removes")


def test_every_expressible_window_is_observable_at_any_allowed_cadence():
    # Windows are minute-resolution, so the shortest a user can express is 60s.
    for cadence in range(SW.MIN_TICK_S, SW.MAX_TICK_S + 1):
        assert SW.window_is_observable(0, cadence), (
            f"a one-minute window must be observable at {cadence}s")


def test_zero_duration_is_a_one_minute_window_not_an_error():
    assert SW.window_is_observable(0, 60) is True
    assert SW.window_is_observable(1, 60) is True


def test_a_window_shorter_than_the_cadence_would_not_be_observable():
    # Not reachable through the UI, but the invariant is stated rather than assumed.
    assert SW.window_is_observable(0, 90) is False
