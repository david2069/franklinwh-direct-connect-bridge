"""Several gateways on one IP, each on its own ports (an emulator host): forces, the
watchdog's SoC reader and Modbus reachability are kept per gateway, not per IP."""
import pytest

from franklinwh_direct_connect_bridge import battery_control as bc
from franklinwh_direct_connect_bridge import state


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    state.reset_gateways()
    bc._clear_active()
    bc.set_host_override("")
    monkeypatch.delenv("FWH_MODBUS_HOST", raising=False)
    monkeypatch.setattr(bc, "_watchdog_loop", lambda *a, **k: None)   # no real threads
    monkeypatch.setattr(bc, "_LAST", {})
    yield
    bc._clear_active()
    state.reset_gateways()


def _two_on_one_ip():
    a = state.register_gateway("gw-a", "10.0.0.5", "A", port=9020, modbus_port=5020)
    b = state.register_gateway("gw-b", "10.0.0.5", "B", port=9021, modbus_port=5021)
    a.last_state, b.last_state = {"soc": 30}, {"soc": 90}
    state.set_default("gw-a")
    return a, b


def test_each_gateway_gets_its_own_modbus_target():
    a, b = _two_on_one_ip()
    assert bc.effective_target(a.active_host) == ("10.0.0.5", 5020)
    assert bc.effective_target(b.active_host) == ("10.0.0.5", 5021)


def test_a_force_on_one_is_not_held_on_the_other():
    a, b = _two_on_one_ip()
    bc._arm_watchdog(a.active_host, "Force Discharge", -1000, 600, 0)
    assert bc.holds_force(a.active_host)
    assert not bc.holds_force(b.active_host)
    assert bc.current(b.active_host)["active"] == "Not Active"


def test_a_second_force_does_not_replace_the_first():
    a, b = _two_on_one_ip()
    bc._arm_watchdog(a.active_host, "Force Discharge", -1000, 600, 0)
    bc._arm_watchdog(b.active_host, "Force Discharge", -2000, 600, 0)
    assert sorted(bc.held_hosts()) == sorted([a.active_host, b.active_host])
    bc._clear_active(b.active_host)
    assert bc.current(a.active_host)["watts"] == -1000


def test_each_force_reads_its_own_gateways_soc():
    a, b = _two_on_one_ip()
    assert bc._gateway_soc(a.active_host)() == 30
    assert bc._gateway_soc(b.active_host)() == 90


def test_reachability_is_recorded_per_gateway():
    a, b = _two_on_one_ip()
    bc._record(a.active_host, "unreachable", "connect", "refused")
    assert bc.last_result(a.active_host)["state"] == "unreachable"
    assert bc.last_result(b.active_host) is None


def test_the_ip_alone_names_no_gateway_when_two_share_it():
    _two_on_one_ip()
    assert bc.effective_target("10.0.0.5") == ("10.0.0.5", 502)
    assert not bc.holds_force("10.0.0.5")
