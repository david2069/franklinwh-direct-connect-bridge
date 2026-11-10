"""#333: FORCE is shown only for a force THIS bridge is holding.

Owner, 2026-10-27: FORCE (a WSet setpoint) and VPP (1707 programme id 9, any remote
controller) are different states. Owner, 2026-10-28: show FORCE only for this bridge's
own forces; the bridge does not poll SunSpec Model 704, so another client's force is VPP.
"""
import time

import pytest

from franklinwh_direct_connect_bridge import app as appmod
from franklinwh_direct_connect_bridge import battery_control as bc
from franklinwh_direct_connect_bridge import state


class _Gw:
    def __init__(self, host, vpp_active=None, cloud_vpp=None):
        self.active_host = host
        self.configured_host = host
        self.vpp_active = vpp_active
        self.cloud_vpp = cloud_vpp
        self.cloud_ts = time.time()
        self.cloud_programme = "Prog A"


@pytest.fixture
def holding():
    def _hold(host):
        with bc._lock:
            bc._active.clear()
            bc._active[bc._host_part(host)] = {"command": "Force Charge", "host": host,
                                               "started": time.time()}
    yield _hold
    with bc._lock:
        bc._active.clear()


def test_own_force_is_force(holding):
    holding("10.0.0.5")
    assert appmod._dispatch_kind(_Gw("10.0.0.5", vpp_active=True)) == ("force", None)


def test_own_force_wins_over_cloud_vpp(holding):
    holding("10.0.0.5:502")
    assert appmod._dispatch_kind(_Gw("10.0.0.5", cloud_vpp=True))[0] == "force"


def test_force_on_another_gateway_is_not_ours(holding):
    holding("10.0.0.6")
    assert appmod._dispatch_kind(_Gw("10.0.0.5", vpp_active=True)) == ("remote", None)


def test_1707_without_our_force_is_remote_not_force():
    assert appmod._dispatch_kind(_Gw("10.0.0.5", vpp_active=True)) == ("remote", None)
    assert appmod._dispatch_kind(_Gw("10.0.0.5", cloud_vpp=True)) == ("vpp", "Prog A")
    assert appmod._dispatch_kind(_Gw("10.0.0.5")) == (None, None)


def test_modbus_host_env_no_longer_counts_for_the_default_gateway(holding, monkeypatch):
    """#379: FWH_MODBUS_HOST is gone; a force is the gateway's only on its own host."""
    gw = _Gw("10.0.0.5", vpp_active=True)
    monkeypatch.setenv("FWH_MODBUS_HOST", "10.9.9.9")
    holding("10.9.9.9")
    monkeypatch.setattr(state, "default_gateway", lambda: gw)
    assert appmod._dispatch_kind(gw)[0] == "remote"


def test_holds_force_is_false_when_idle():
    assert bc.holds_force("10.0.0.5") is False
