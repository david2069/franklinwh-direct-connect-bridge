"""Modbus host/port override + effective_target (Control-tab connection setup)."""

from franklinwh_direct_connect_bridge import battery_control as bc
from franklinwh_direct_connect_bridge import client as client_mod


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


# --- #30 / #32: the Modbus probe is tri-state, and it honours the disable switch ----------

def test_probe_modbus_returns_none_when_disabled_and_opens_no_socket(monkeypatch):
    """Disabled here means no socket, and 'not probed' — never a confident False.

    The socket is what matters: a probe that returns None but still connected would keep
    breaking the owner's "Modbus is off" guarantee during a correlation window (#32).
    """
    opened: list[tuple] = []
    monkeypatch.setattr(client_mod.discover, "port_open",
                        lambda h, p, timeout=0: opened.append((h, p)) or True)
    monkeypatch.setattr(bc, "is_enabled", lambda: False)

    assert client_mod._probe_modbus("192.0.2.10") is None
    assert opened == [], f"probe opened a socket while Modbus is disabled: {opened}"


def test_probe_modbus_opens_no_socket_when_enabled(monkeypatch):
    """#221: enabled no longer means probed. The answer is the last real connection."""
    opened: list[tuple] = []
    monkeypatch.setattr(client_mod.discover, "port_open",
                        lambda h, p, timeout=0: opened.append((h, p)) or True)
    monkeypatch.setattr(bc, "is_enabled", lambda: True)
    monkeypatch.setattr(bc, "_LAST", {})

    assert client_mod._probe_modbus("192.0.2.10") is None      # nothing measured yet
    bc._record("192.0.2.10", "ready", "status")
    assert client_mod._probe_modbus("192.0.2.10") is True
    assert opened == [], f"probe opened a socket: {opened}"


def test_probe_modbus_false_when_last_connect_refused(monkeypatch):
    monkeypatch.setattr(client_mod.discover, "port_open", lambda h, p, timeout=0: True)
    monkeypatch.setattr(bc, "is_enabled", lambda: True)
    monkeypatch.setattr(bc, "_LAST", {})
    bc._record("192.0.2.10", "unreachable", "connect", "refused")
    assert client_mod._probe_modbus("192.0.2.10") is False


def test_probe_modbus_none_for_a_mock_gateway(monkeypatch):
    opened: list[tuple] = []
    monkeypatch.setattr(client_mod.discover, "port_open",
                        lambda h, p, timeout=0: opened.append((h, p)) or True)
    assert client_mod._probe_modbus("192.0.2.10", mock=True) is None
    assert opened == []
