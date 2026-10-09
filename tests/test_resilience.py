"""The shared boundary-call pattern: deadline, classified retry, outcome, report.

The behaviour that matters most here is the UNKNOWN verdict. A write that times
out after the request left has not failed — and retrying it blind is how you
dispatch a battery twice.
"""
import socket

import pytest

from franklinwh_direct_connect_bridge import resilience as R


def _raiser(*excs):
    """Return a callable that raises each exc in turn, then returns 'done'."""
    seq = list(excs)

    def fn():
        if seq:
            raise seq.pop(0)
        return "done"
    return fn


# ── classification ────────────────────────────────────────────────────────────
@pytest.mark.parametrize("exc", [TimeoutError(), ConnectionResetError(), socket.gaierror(),
                                 OSError("eio"), ConnectionRefusedError()])
def test_transport_faults_are_transient(exc):
    assert R.is_transient(exc)


@pytest.mark.parametrize("exc", [ValueError("bad"), TypeError(), NotImplementedError(),
                                 PermissionError(), KeyError("k")])
def test_caller_and_device_rejections_are_permanent(exc):
    assert not R.is_transient(exc)


def test_permanent_wins_over_transient_for_oserror_subclasses():
    # PermissionError subclasses OSError; misclassifying it would retry a refusal.
    assert not R.is_transient(PermissionError("denied"))


# ── reads ─────────────────────────────────────────────────────────────────────
def test_transient_read_is_retried_then_succeeds():
    out = R.call(_raiser(TimeoutError()), action="power_flow",
                 policy=R.RetryPolicy(attempts=3, base_delay_s=0))
    assert out.ok and out.attempts == 2 and out.value == "done"


def test_permanent_read_is_not_retried():
    out = R.call(_raiser(ValueError("nope"), ValueError("nope")), action="power_flow",
                 policy=R.RetryPolicy(attempts=5, base_delay_s=0))
    assert out.verdict is R.Verdict.FAILED
    assert out.attempts == 1, "a permanent error must not burn retries"


def test_attempts_are_capped_and_the_outcome_is_failed():
    out = R.call(_raiser(*[TimeoutError()] * 10), action="power_flow",
                 policy=R.RetryPolicy(attempts=3, base_delay_s=0))
    assert out.verdict is R.Verdict.FAILED and out.attempts == 3


def test_deadline_stops_retrying_even_with_attempts_left():
    out = R.call(_raiser(*[TimeoutError()] * 50), action="slow",
                 policy=R.RetryPolicy(attempts=50, base_delay_s=0.01, deadline_s=0.05))
    assert out.verdict is R.Verdict.FAILED
    assert out.attempts < 50 and out.elapsed_s < 2.0


# ── writes: the UNKNOWN rule ──────────────────────────────────────────────────
def test_write_that_times_out_is_unknown_not_failed():
    out = R.call(_raiser(TimeoutError()), action="force_charge", target="gw1",
                 write=True, policy=R.RetryPolicy(attempts=3, base_delay_s=0))
    assert out.verdict is R.Verdict.UNKNOWN
    assert out.attempts == 1, "an ambiguous write must not be retried"
    assert "may have been applied" in out.detail


def test_write_refused_before_arrival_is_retried_not_marked_unknown():
    # Connection refused means the bytes never left — unambiguous, so unlike a
    # timeout this IS retried, and a later success stands.
    out = R.call(_raiser(ConnectionRefusedError(), ConnectionRefusedError()),
                 action="force_charge", write=True,
                 policy=R.RetryPolicy(attempts=3, base_delay_s=0))
    assert out.ok and out.attempts == 3


def test_write_refused_every_time_is_failed_never_unknown():
    out = R.call(_raiser(*[ConnectionRefusedError()] * 5), action="force_charge", write=True,
                 policy=R.RetryPolicy(attempts=3, base_delay_s=0))
    assert out.verdict is R.Verdict.FAILED, "it never arrived, so it is not ambiguous"
    assert out.attempts == 3


def test_write_unknown_can_be_retried_only_when_policy_opts_in():
    out = R.call(_raiser(TimeoutError()), action="set_mode", write=True,
                 policy=R.RetryPolicy(attempts=3, base_delay_s=0, retry_unknown=True))
    assert out.ok and out.attempts == 2


def test_read_that_times_out_is_failed_not_unknown():
    out = R.call(_raiser(*[TimeoutError()] * 3), action="power_flow",
                 policy=R.RetryPolicy(attempts=2, base_delay_s=0))
    assert out.verdict is R.Verdict.FAILED, "only writes can be ambiguous"


# ── reporting: audit + notify ─────────────────────────────────────────────────
class _Spy:
    def __init__(self):
        self.audits, self.notes = [], []

    def audit(self, action, *, detail="", result="", ok=None):
        self.audits.append((action, ok, result))

    def notify(self, title, message):
        self.notes.append((title, message))


def test_writes_are_audited_and_reads_are_not():
    spy = _Spy()
    R.call(lambda: "x", action="set_mode", write=True, audit=spy.audit, notifier=spy)
    R.call(lambda: "x", action="power_flow", audit=spy.audit, notifier=spy)
    assert [a[0] for a in spy.audits] == ["set_mode"]


def test_unknown_write_notifies_with_a_distinct_title():
    spy = _Spy()
    R.call(_raiser(TimeoutError()), action="force_charge", write=True,
           policy=R.RetryPolicy(attempts=1, base_delay_s=0),
           audit=spy.audit, notifier=spy)
    assert len(spy.notes) == 1
    assert "UNKNOWN" in spy.notes[0][0]


def test_successful_write_does_not_notify():
    spy = _Spy()
    R.call(lambda: "x", action="set_mode", write=True, audit=spy.audit, notifier=spy)
    assert spy.notes == []


def test_a_broken_hook_never_breaks_the_call():
    class Boom:
        def notify(self, *a, **k):
            raise RuntimeError("notifier down")

    def bad_audit(*a, **k):
        raise RuntimeError("audit down")

    out = R.call(lambda: "x", action="set_mode", write=True,
                 audit=bad_audit, notifier=Boom())
    assert out.ok, "observability must never fail the action"


# ── the contract the scheduler needs ──────────────────────────────────────────
def test_outcome_is_structured_not_stringly_typed():
    out = R.call(_raiser(TimeoutError()), action="force_charge", target="gw1", write=True,
                 policy=R.RetryPolicy(attempts=1, base_delay_s=0))
    assert out.ok is False
    assert out.needs_attention is True
    assert out.as_dict()["verdict"] == "unknown"
    assert "force_charge" in out.render() and "gw1" in out.render()


def test_backoff_grows_and_is_bounded():
    p = R.RetryPolicy(base_delay_s=1.0, max_delay_s=8.0, jitter=0.0)
    assert [p.delay_for(i) for i in (1, 2, 3, 4, 9)] == [1.0, 2.0, 4.0, 8.0, 8.0]
