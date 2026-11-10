"""Dispatch is gated on a CONFIRMED Modbus path, not on configuration.

Owner, 2026-10-15, planning a field deployment: "If Modbus is NOT configured or confirmed
we need to disable the UI and force charge/discharge functions."

The distinction that matters: a socket that opens is not a dispatch path. :502 answering
proves a listener exists — the same mistake as probing a secured REST API with an
unauthenticated health endpoint and calling it available (#56). Confirmation here is a
SunSpec read that RETURNS.
"""
import pytest

from franklinwh_direct_connect_bridge import battery_control as bc


class _Ctl:
    """A controller stub standing in for the library's, at the connect boundary."""
    def __init__(self, *, sunspec=True):
        self._sunspec = sunspec
        self.commands = []

    def read_control_status(self):
        if not self._sunspec:
            raise OSError("no response from unit 1")
        return {"wset_enabled": False, "wset_pct": 0}

    def discover_ratings(self):
        self.RATED_MAX_CHARGE_W = self.RATED_MAX_DISCHARGE_W = 5000

    def send_command(self, cmd, dry_run=False):
        self.commands.append(cmd)
        return True, "sent"

    def reset_control_state(self):
        self.commands.append("reset")

    def disconnect(self):
        pass


@pytest.fixture(autouse=True)
def _enabled(monkeypatch):
    monkeypatch.setattr(bc, "_ENABLED", True)
    monkeypatch.setattr(bc, "_lib", lambda: (object, lambda **kw: kw))
    bc._clear_active()
    yield
    bc._clear_active()


def _connects_to(monkeypatch, ctl):
    monkeypatch.setattr(bc, "_connect", lambda host: (ctl, lambda **kw: kw))


# -- the four states ---------------------------------------------------------------------
def test_no_host_is_not_configured():
    out = bc.capability("")
    assert out["state"] == "not_configured" and out["ready"] is False
    assert out["hint"]                                   # every state carries a remedy


def test_switched_off_is_not_configured(monkeypatch):
    monkeypatch.setattr(bc, "_ENABLED", False)
    assert bc.capability("192.0.2.110")["state"] == "not_configured"


def test_a_refused_socket_is_unreachable(monkeypatch):
    def _boom(host):
        raise ConnectionError("could not connect to aGate Modbus at 192.0.2.110:502")
    monkeypatch.setattr(bc, "_connect", _boom)
    out = bc.capability("192.0.2.110")
    assert out["state"] == "unreachable" and out["ready"] is False
    assert "502" in out["reason"]


def test_a_socket_that_opens_but_does_not_speak_sunspec_is_not_ready(monkeypatch):
    """THE case this exists for: the port answers, so a connect-only probe says 'up'."""
    _connects_to(monkeypatch, _Ctl(sunspec=False))
    out = bc.capability("192.0.2.110")
    assert out["state"] == "no_sunspec" and out["ready"] is False
    assert "sunsMdEn" in out["hint"]                     # points at the actual setting


def test_a_successful_sunspec_read_is_ready(monkeypatch):
    _connects_to(monkeypatch, _Ctl())
    out = bc.capability("192.0.2.110")
    assert out["state"] == "ready" and out["ready"] is True
    assert out["hint"] == ""


# -- the gate is the API, not the UI -----------------------------------------------------
def test_a_force_is_refused_when_sunspec_does_not_answer(monkeypatch):
    ctl = _Ctl(sunspec=False)
    _connects_to(monkeypatch, ctl)
    out = bc.execute("Force Charge", host="192.0.2.110", power_pct=50)
    assert out["ok"] is False and out["state"] == "no_sunspec"
    assert ctl.commands == []                            # nothing was written


def test_a_force_is_refused_when_unreachable(monkeypatch):
    def _boom(host):
        raise ConnectionError("refused")
    monkeypatch.setattr(bc, "_connect", _boom)
    out = bc.execute("Force Discharge", host="192.0.2.110", power_pct=50)
    assert out["ok"] is False and out["state"] == "unreachable"


def test_a_force_goes_through_when_the_path_is_confirmed(monkeypatch):
    ctl = _Ctl()
    _connects_to(monkeypatch, ctl)
    out = bc.execute("Force Charge", host="192.0.2.110", power_pct=50, duration_s=60)
    assert out["ok"] is True
    assert ctl.commands                                   # it really wrote
    # and the bridge's own watchdog is holding the deadline
    assert bc.current().get("active") == "Force Charge"
    assert bc.current().get("remaining_s") is not None


def test_release_is_never_blocked_by_an_unhealthy_path(monkeypatch):
    """Refusing to STOP a dispatch because the path looks unhealthy is the wrong way round."""
    ctl = _Ctl(sunspec=False)
    _connects_to(monkeypatch, ctl)
    out = bc.execute("Release", host="192.0.2.110")
    assert out["ok"] is True and "reset" in ctl.commands
