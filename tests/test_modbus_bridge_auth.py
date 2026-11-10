"""#56 — the Modbus Bridge REST path must authenticate, and say honestly what it can do.

Measured facts this pins, from a live Modbus Bridge on 2026-10-15:

  GET  /api/health   unauthenticated -> 200      <- what availability used to be probed on
  POST /api/command  unauthenticated -> 401
  POST /api/command  as viewer       -> 403 "'control' capability required"
  POST /api/command  as admin        -> 200

So a health probe says "ready" for a path that 401s, and a correct password on the wrong
ACCOUNT fails differently again. All four states must be distinguishable.
"""
import json
import urllib.error

import pytest

from franklinwh_direct_connect_bridge import modbus_bridge as mb


@pytest.fixture(autouse=True)
def _clear():
    mb.reset()
    yield
    mb.reset()


class _Resp:
    def __init__(self, payload): self._b = json.dumps(payload).encode()
    def read(self): return self._b
    def __enter__(self): return self
    def __exit__(self, *a): return False


def _login_returns(caps, monkeypatch, calls=None):
    def _open(opener, url, data=None, timeout=0):
        if calls is not None:
            calls.append(url)
        return _Resp({"capabilities": caps, "user": {"username": "x"}})
    monkeypatch.setattr(mb, "_open", _open)


def _http_error(code):
    def _open(opener, url, data=None, timeout=0):
        raise urllib.error.HTTPError(url, code, "nope", {}, None)
    return _open


# --- the four states ----------------------------------------------------------------------

def test_control_capability_is_ready(monkeypatch):
    _login_returns(["view", "control"], monkeypatch)
    st = mb.status("http://bridge", "admin", "pw")
    assert st["state"] == "ready" and st["reason"] is None


def test_viewer_is_forbidden_not_ready(monkeypatch):
    """The nastiest case: password correct, login fine, dispatch impossible."""
    _login_returns(["view"], monkeypatch)
    st = mb.status("http://bridge", "demo", "demo")
    assert st["state"] == "forbidden"
    assert "control" in st["reason"] and "account" in st["reason"].lower()


def test_bad_credentials_are_unauthenticated(monkeypatch):
    monkeypatch.setattr(mb, "_open", _http_error(401))
    assert mb.status("http://bridge", "x", "y")["state"] == "unauthenticated"


def test_host_down_is_unreachable(monkeypatch):
    def _boom(opener, url, data=None, timeout=0):
        raise OSError("connection refused")
    monkeypatch.setattr(mb, "_open", _boom)
    assert mb.status("http://bridge", "x", "y")["state"] == "unreachable"


def test_no_credentials_configured_is_unauthenticated(monkeypatch):
    """Not 'unreachable' — the host may be perfectly fine; we simply cannot sign in."""
    assert mb.status("http://bridge", "", "")["state"] == "unauthenticated"


def test_no_url_is_unreachable():
    assert mb.status("", "u", "p")["state"] == "unreachable"


# --- the session --------------------------------------------------------------------------

def test_session_is_reused_not_relogged_per_command(monkeypatch):
    calls = []
    _login_returns(["control"], monkeypatch, calls)
    mb.status("http://bridge", "u", "p")
    mb.status("http://bridge", "u", "p")
    mb.status("http://bridge", "u", "p")
    assert len(calls) == 1, "logging in per call would be slow and noisy in their audit trail"


def test_expired_session_re_logs_in_once(monkeypatch):
    state = {"n": 0}

    def _open(opener, url, data=None, timeout=0):
        if url.endswith(mb.LOGIN_PATH):
            return _Resp({"capabilities": ["control"]})
        state["n"] += 1
        if state["n"] == 1:
            raise urllib.error.HTTPError(url, 401, "expired", {}, None)
        return _Resp({"ok": True})

    monkeypatch.setattr(mb, "_open", _open)
    assert mb.post_command("http://bridge", "u", "p", "battery_command", "Release") == {"ok": True}
    assert state["n"] == 2, "it should retry exactly once after re-authenticating"


def test_forbidden_command_says_which_problem_it_is(monkeypatch):
    def _open(opener, url, data=None, timeout=0):
        if url.endswith(mb.LOGIN_PATH):
            return _Resp({"capabilities": ["view"]})
        raise urllib.error.HTTPError(url, 403, "no", {}, None)

    monkeypatch.setattr(mb, "_open", _open)
    with pytest.raises(mb.AuthError) as e:
        mb.post_command("http://bridge", "demo", "demo", "battery_command", "Release")
    assert e.value.state == "forbidden" and "control" in str(e.value)


# --- the provider ---------------------------------------------------------------------------

def test_provider_availability_is_authorisation_not_liveness(monkeypatch):
    """A secured bridge answers an anonymous /api/health with 200. That is not availability."""
    from franklinwh_direct_connect_bridge import providers

    class S:
        modbus_bridge_url = "http://bridge"
        modbus_bridge_username = "demo"
        modbus_bridge_password = "demo"
        modbus_host = ""
        fwh_host = ""

    # The health probe says YES. Authorisation says no. Availability must follow
    # authorisation — this is the exact substitution that made the defect invisible.
    monkeypatch.setattr(providers, "_probe_url", lambda *a, **k: True)
    _login_returns(["view"], monkeypatch)          # viewer: health 200, command 403
    prov = providers.dispatch_provider(S())
    rest = next(c for c in prov["candidates"] if c["kind"] == "modbus-bridge")
    assert rest["available"] is False, "availability followed the health probe again"
    assert rest["auth"] == "forbidden"


def test_unknown_slug_is_rejected_not_an_auth_error(monkeypatch):
    """Their PR #100 returns 400 for an unknown slug. It is not a credentials problem and
    must not be reported as one — nor arrive as a bare traceback."""
    import io

    def _open(opener, url, data=None, timeout=0):
        if url.endswith(mb.LOGIN_PATH):
            return _Resp({"capabilities": ["control"]})
        raise urllib.error.HTTPError(
            url, 400, "Bad Request", {},
            io.BytesIO(json.dumps({"detail": "Unknown command 'nope'. Known: battery_command"}).encode()))

    monkeypatch.setattr(mb, "_open", _open)
    with pytest.raises(mb.CommandRejected) as e:
        mb.post_command("http://bridge", "u", "p", "nope", "1")
    assert "Unknown command" in str(e.value) and "400" in str(e.value)
    assert not isinstance(e.value, mb.AuthError)
