"""#213 — a force above the battery's rating must keep its direction.

franklinwh-modbus 0.9.5's own safety clamp returns the rating with the OPPOSITE sign, so an
over-rating Force Charge reached the battery as a full-rate discharge. The bridge now limits
the magnitude itself, keeping the sign, before the library sees it. The fake controller
below runs the library's REAL ``_validate_power`` on whatever the bridge sends."""
import pytest

from franklinwh_direct_connect_bridge import battery_control as bc

pytest.importorskip("franklinwh_modbus")
from franklinwh_modbus.controller import FranklinWHController  # noqa: E402


class _Cmd:
    def __init__(self, power_watts):
        self.power_watts = power_watts


def _fake_controller(rating_ch=5000, rating_dis=4000):
    c = object.__new__(FranklinWHController)
    c.RATED_MAX_CHARGE_W, c.RATED_MAX_DISCHARGE_W = rating_ch, rating_dis
    c.sent = []

    def send_command(cmd, dry_run=False):
        applied = c._validate_power(cmd.power_watts)     # the library's own clamp
        c.sent.append((cmd.power_watts, applied))
        return True, f"sent {applied}W"
    c.send_command = send_command
    return c


@pytest.fixture
def ctl(monkeypatch):
    c = _fake_controller()
    monkeypatch.setattr(bc, "capability", lambda host: {"ready": True, "reason": "", "state": "ready", "hint": ""})
    monkeypatch.setattr(bc, "_connect", lambda host: (c, _Cmd))
    monkeypatch.setattr(bc, "_close", lambda c: None)
    return c


def _run(cmd, **kw):
    return bc.execute(cmd, host="192.0.2.10", dry_run=True, **kw)


def test_over_rating_charge_still_charges(ctl):
    out = _run("Force Charge", power_w=8000, power_mode="w")
    assert ctl.sent == [(5000, 5000)]          # limited, and still a charge
    assert out["watts"] == 5000 and "limited to the 5000W rating" in out["result"]


def test_over_rating_discharge_still_discharges(ctl):
    out = _run("Force Discharge", power_w=9000, power_mode="w")
    assert ctl.sent == [(-4000, -4000)]
    assert out["watts"] == -4000


def test_a_negative_watt_value_takes_the_command_direction(ctl):
    _run("Force Charge", power_w=-3000, power_mode="w")
    assert ctl.sent == [(3000, 3000)]


def test_percent_is_bounded_to_0_100(ctl):
    _run("Force Charge", power_pct=150, power_mode="pct")
    _run("Force Discharge", power_pct=-20, power_mode="pct")
    assert ctl.sent == [(5000, 5000), (0, 0)]


def test_within_rating_is_unchanged(ctl):
    out = _run("Force Discharge", power_w=2500, power_mode="w")
    assert ctl.sent == [(-2500, -2500)] and "limited" not in out["result"]
