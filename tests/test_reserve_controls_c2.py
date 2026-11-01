"""C2: reserve SoC per mode as Home Assistant numbers, written through the cloud.

The aGate discards a local reserve write, so the controls exist only when the cloud can
write this gateway; their state is the local 1726 read the poll already makes. The cloud
call is stubbed (providers.set_reserve); nothing here signs in."""
import pytest

from franklinwh_direct_connect_bridge import config, providers
from franklinwh_direct_connect_bridge.publish import entities, handle_command
from franklinwh_direct_connect_bridge.state import GatewayState


def _modes():
    return {"power": {}, "mode": {"modes": [
        {"name": "Time-of-Use", "workmode": 1, "reserved_soc": 15, "active": False},
        {"name": "Self-Consumption", "workmode": 2, "reserved_soc": 8, "active": True},
        {"name": "Emergency Backup", "workmode": 3, "reserved_soc": 100, "active": False}]}}


def test_each_modes_reserve_comes_from_the_poll():
    st = entities.state_payload(_modes())
    assert (st["reserve_tou_pct"], st["reserve_self_pct"]) == (15, 8)
    assert "reserve_backup_pct" not in st


def test_reserve_numbers_are_published_unless_skipped():
    cfgs, _, _ = entities.discovery_configs("n", {}, "p", "d", ["controls"])
    by_topic = dict(cfgs)
    tou = by_topic["d/number/n/reserve_soc_tou/config"]
    assert (tou["min"], tou["max"], tou["step"], tou["unit_of_measurement"]) == (0, 100, 1, "%")
    assert tou["command_topic"] == "p/n/control/reserve_soc_tou/set"
    assert tou["value_template"] == "{{ value_json.reserve_tou_pct }}"
    cfgs, _, _ = entities.discovery_configs("n", {}, "p", "d", ["controls"],
                                            skip=entities.RESERVE_KEYS)
    assert not any("reserve_soc" in t for t, _ in cfgs)
    assert entities.RESERVE_KEYS <= entities.MOCK_ABSENT_KEYS


@pytest.fixture
def s(monkeypatch):
    s = config.get_settings()
    monkeypatch.setattr(s, "fwh_cloud_email", "owner@example.invalid")
    monkeypatch.setattr(s, "fwh_cloud_password", "x")
    monkeypatch.setattr(s, "fwh_cloud_gateway", "")
    return s


def _gw(serial="10060006A02F00000001", locked=True, mock=False):
    g = GatewayState(id="gw1", label="Home", configured_host="10.0.0.5")
    g.serial, g.serial_locked, g.is_mock = serial, locked, mock
    return g


def test_the_cloud_can_write_only_its_own_locked_gateway(s, monkeypatch):
    ok = dict(serial="10060006A02F00000001", serial_locked=True, is_mock=False)
    assert providers.cloud_can_write(s, **ok)
    assert not providers.cloud_can_write(s, **{**ok, "serial_locked": False})
    assert not providers.cloud_can_write(s, **{**ok, "is_mock": True})
    monkeypatch.setattr(s, "fwh_cloud_gateway", "10060006A02F00000002")
    assert not providers.cloud_can_write(s, **ok)
    monkeypatch.setattr(s, "fwh_cloud_gateway", "")
    monkeypatch.setattr(s, "fwh_cloud_password", "")
    assert not providers.cloud_can_write(s, **ok)


class _NoLocal:
    def __getattr__(self, name):
        raise AssertionError(f"a reserve must never go to the local API ({name})")


def test_a_reserve_command_goes_to_the_cloud_for_this_gateway(s, monkeypatch):
    calls = []
    monkeypatch.setattr(providers, "set_reserve",
                        lambda st, mode, soc, *, serial: calls.append((mode, soc, serial)) or {"ok": True})
    out = handle_command("reserve_soc_tou", "20.0", settings=s, client=_NoLocal(),
                         gateway=_gw(serial="10060006a02f00000001"))
    assert calls == [("tou", 20, "10060006A02F00000001")]
    assert out == "reserve tou -> 20%: applied via cloud"


def test_a_reserve_command_is_refused_before_any_cloud_call(s, monkeypatch):
    monkeypatch.setattr(providers, "set_reserve",
                        lambda *a, **k: pytest.fail("no cloud call expected"))
    assert "serial hasn't been read" in handle_command(
        "reserve_soc_self", "30", settings=s, client=_NoLocal(), gateway=_gw(locked=False))
    assert "mock gateway" in handle_command(
        "reserve_soc_self", "30", settings=s, client=_NoLocal(), gateway=_gw(mock=True))
    assert "not a number" in handle_command(
        "reserve_soc_self", "lots", settings=s, client=_NoLocal(), gateway=_gw())


def test_a_cloud_failure_is_the_answer_not_a_raise(s, monkeypatch):
    def boom(*a, **k):
        raise providers.ReserveUnavailable("no provider")
    monkeypatch.setattr(providers, "set_reserve", boom)
    out = handle_command("reserve_soc_self", "10", settings=s, client=_NoLocal(), gateway=_gw())
    assert out.startswith("reserve self -> 10%: failed: ReserveUnavailable")


def test_emergency_backup_has_no_reserve_control(s, monkeypatch):
    """Its reserve is fixed at 100 % and can't be changed (owner, 2026-10-31)."""
    monkeypatch.setattr(providers, "set_reserve", lambda *a, **k: pytest.fail("no cloud call"))
    assert "reserve_soc_backup" not in entities.RESERVE_KEYS
    assert handle_command("reserve_soc_backup", "50", settings=s, client=_NoLocal(),
                          gateway=_gw()) == "unknown control 'reserve_soc_backup'"
