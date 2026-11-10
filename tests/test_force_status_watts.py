"""franklinwh-modbus 0.10.1 writes a force as watts (WSetMod=1 + WSet) and leaves WSetPct
at 0. status() must read the field the active mode uses, or a running force shows as
"Force Standby". Library sign: WSet positive = discharge, negative = charge."""
import pytest

from franklinwh_direct_connect_bridge import battery_control as bc


class _C:
    def __init__(self, cs):
        self.cs = cs

    def read_control_status(self):
        return self.cs

    def disconnect(self):
        pass


@pytest.fixture
def run(monkeypatch):
    def _run(cs):
        monkeypatch.setattr(bc, "available", lambda: (True, ""))
        monkeypatch.setattr(bc, "is_mock_target", lambda h: False)
        monkeypatch.setattr(bc, "_connect", lambda h: (_C(cs), None))
        monkeypatch.setattr(bc, "_ratings", lambda c: (5000, 5000))
        monkeypatch.setattr(bc, "_record", lambda *a, **k: None)
        return bc.status("192.0.2.10")["active"]
    return _run


def test_watts_mode_discharge_is_not_standby(run):
    assert run({"wset_enabled": 1, "wset_mode": 1, "wset_watts": 1000, "wset_pct": 0}) \
        == "Force Discharge"


def test_watts_mode_charge(run):
    assert run({"wset_enabled": 1, "wset_mode": 1, "wset_watts": -1000, "wset_pct": 0}) \
        == "Force Charge"


def test_watts_mode_zero_is_standby(run):
    assert run({"wset_enabled": 1, "wset_mode": 1, "wset_watts": 0, "wset_pct": 0}) \
        == "Force Standby"


def test_percent_mode_still_read_from_wset_pct(run):
    """A force set by something else in percent mode (WSetMod 0) keeps working."""
    assert run({"wset_enabled": 1, "wset_mode": 0, "wset_watts": 0, "wset_pct": 20}) \
        == "Force Discharge"


def test_not_enabled_is_not_active(run):
    assert run({"wset_enabled": 0, "wset_mode": 1, "wset_watts": 1000}) == "Not Active"
