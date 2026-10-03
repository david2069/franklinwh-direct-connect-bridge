"""Modbus host/port override + effective_target (Control-tab connection setup)."""

from franklinwh_local_bridge import battery_control as bc


def _reset():
    bc.set_host_override("", 0)


def test_effective_target_auto_splits_gateway_host():
    _reset()
    # bare IP -> default 502
    assert bc.effective_target("192.168.0.110") == ("192.168.0.110", 502)
    # a mock's ip:port is split (not resolved as a hostname)
    assert bc.effective_target("127.0.0.1:44075") == ("127.0.0.1", 44075)
    # empty host -> ("", 502)
    assert bc.effective_target("") == ("", 502)


def test_override_wins_over_gateway_host():
    _reset()
    bc.set_host_override("10.0.0.5", 1502)
    try:
        # override applies regardless of the passed gateway host
        assert bc.effective_target("192.168.0.110") == ("10.0.0.5", 1502)
        assert bc.host_override() == {"host": "10.0.0.5", "port": 1502}
    finally:
        _reset()


def test_override_embedded_port_beats_arg():
    _reset()
    bc.set_host_override("10.0.0.9:1600", 1502)   # embedded :1600 wins
    try:
        assert bc.effective_target("x") == ("10.0.0.9", 1600)
    finally:
        _reset()


def test_override_default_port_when_unspecified():
    _reset()
    bc.set_host_override("10.0.0.7")   # no port -> default 502
    try:
        assert bc.effective_target("x") == ("10.0.0.7", 502)
        assert bc.host_override()["port"] is None
    finally:
        _reset()


def test_clear_override_returns_to_auto():
    bc.set_host_override("10.0.0.5", 1502)
    bc.set_host_override("", 0)
    assert bc.host_override() == {"host": "", "port": None}
    assert bc.effective_target("192.168.0.110") == ("192.168.0.110", 502)
