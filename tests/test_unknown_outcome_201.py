"""#201: a device write that timed out may have landed, so the scheduler records UNKNOWN and
does not send it again; a refused connection is still a failure to retry. The resilience
audit hook is called the way resilience calls it, and no longer fails silently."""
from franklinwh_direct_connect_bridge import resilience as R
from franklinwh_direct_connect_bridge import scheduler as SCH


def _outcome(monkeypatch, text, kind="force"):
    calls = []

    def fake_run_action(action, **kw):
        calls.append(1)
        return text
    monkeypatch.setattr(SCH, "run_action", fake_run_action)
    out = SCH.run_action_outcome({"kind": kind}, settings=None, client=None, store=None,
                                 snapshot={}, host="h", gateway_id="gw1")
    return out, len(calls)


def test_a_force_that_timed_out_is_unknown_and_sent_once(monkeypatch):
    out, n = _outcome(monkeypatch, "force charge failed: TimeoutError: timed out")
    assert out.verdict is R.Verdict.UNKNOWN and n == 1


def test_a_mode_write_with_no_reply_is_unknown(monkeypatch):
    out, _ = _outcome(monkeypatch, "mode -> tou: failed: ReadTimeout: read timed out",
                      kind="set_mode")
    assert out.verdict is R.Verdict.UNKNOWN


def test_a_refused_connection_is_still_a_failure(monkeypatch):
    out, _ = _outcome(monkeypatch,
                      "force charge failed: ConnectionRefusedError: [Errno 61] refused")
    assert out.verdict is R.Verdict.FAILED


def test_a_connect_timeout_never_left_so_it_is_a_failure(monkeypatch):
    out, _ = _outcome(monkeypatch, "mode -> tou: failed: ConnectTimeout: timed out")
    assert out.verdict is R.Verdict.FAILED


def test_a_rejected_write_is_still_a_failure(monkeypatch):
    out, _ = _outcome(monkeypatch, "mode -> tou: failed: {'ok': False, 'result': 3}",
                      kind="set_mode")
    assert out.verdict is R.Verdict.FAILED


class _Store:
    def __init__(self):
        self.rows = []

    def log_schedule_event(self, sid, name, status, result, **kw):
        self.rows.append((status, result))


def test_the_audit_hook_takes_resilience_s_call():
    st = _Store()
    sink = SCH._audit_action(st, "s1", "nightly", "gw1")
    # As resilience._report calls it. A retried call gets a row of its own; a single
    # attempt does not, because the scheduler logs each attempt itself.
    sink("force", detail="gw1", result="force[gw1] · ok · 3 attempts", ok=True,
         verdict="ok", attempts=3)
    sink("force", detail="gw1", result="force[gw1] · ok", ok=True, verdict="ok", attempts=1)
    assert st.rows == [("retried", "force[gw1] · ok · 3 attempts")]


def test_resilience_calls_the_hook_with_the_attempts():
    seen = []
    R.call(lambda: "done", action="force", target="gw1", write=True,
           audit=lambda action, **kw: seen.append((action, kw)))
    (action, kw), = seen
    assert action == "force" and kw["attempts"] == 1 and kw["verdict"] == "ok"
