"""#129: a scheduled reserve_soc action sets the reserve through the cloud provider, for
the schedule's own gateway, as POST /api/cloud/reserve does. Without a provider it is
skipped with the reason. The cloud call is stubbed (providers.set_reserve); nothing here
signs in."""
import pytest

from franklinwh_direct_connect_bridge import config, providers, resilience, scheduler, state
from franklinwh_direct_connect_bridge.state import GatewayState


@pytest.fixture
def s(monkeypatch):
    s = config.get_settings()
    monkeypatch.setattr(s, "fwh_cloud_email", "owner@example.invalid")
    monkeypatch.setattr(s, "fwh_cloud_password", "x")
    monkeypatch.setattr(s, "fwh_cloud_gateway", "")
    return s


@pytest.fixture
def gw(monkeypatch):
    g = GatewayState(id="gw129", label="Home", configured_host="10.0.0.5")
    g.serial, g.serial_locked, g.is_mock = "10060006a02f00000001", True, False
    monkeypatch.setattr(state, "get_gateway", lambda i: g if i == "gw129" else None)
    return g


class _NoLocal:
    def __getattr__(self, name):
        raise AssertionError(f"a reserve must never go to the local API ({name})")


def _run(s, action, gateway_id="gw129", **kw):
    return scheduler.run_action_outcome(action, settings=s, client=_NoLocal(), store=None,
                                        snapshot={}, gateway_id=gateway_id, **kw)


def test_a_scheduled_reserve_is_set_through_the_cloud(s, gw, monkeypatch):
    calls = []
    monkeypatch.setattr(providers, "set_reserve",
                        lambda st, mode, soc, *, serial: calls.append((mode, soc, serial)) or {"ok": True})
    out = _run(s, {"kind": "reserve_soc", "mode": "tou", "soc": "25"})
    assert calls == [("tou", 25, "10060006A02F00000001")]
    assert out.verdict is resilience.Verdict.OK
    assert out.detail == "reserve tou -> 25%: applied via cloud"


def test_without_a_cloud_provider_it_is_skipped_with_the_reason(s, gw, monkeypatch):
    def none(*a, **k):
        raise providers.ReserveUnavailable("no reserve provider")
    monkeypatch.setattr(providers, "set_reserve", none)
    out = _run(s, {"kind": "reserve_soc", "mode": "self", "soc": 30})
    assert out.verdict is resilience.Verdict.SKIPPED
    assert "no reserve provider" in out.detail


def test_a_gateway_the_cloud_cant_write_is_skipped_before_any_call(s, gw, monkeypatch):
    monkeypatch.setattr(providers, "set_reserve", lambda *a, **k: pytest.fail("no cloud call"))
    gw.serial_locked = False
    out = _run(s, {"kind": "reserve_soc", "mode": "self", "soc": 30})
    assert out.verdict is resilience.Verdict.SKIPPED and "serial hasn't been read" in out.detail
    out = _run(s, {"kind": "reserve_soc", "mode": "self", "soc": 30}, gateway_id="other")
    assert out.verdict is resilience.Verdict.SKIPPED


def test_a_cloud_error_is_a_failure(s, gw, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("cloud down")
    monkeypatch.setattr(providers, "set_reserve", boom)
    out = _run(s, {"kind": "reserve_soc", "mode": "tou", "soc": 20})
    assert out.verdict is resilience.Verdict.FAILED and "cloud down" in out.detail


def test_a_dry_run_writes_nothing(s, gw, monkeypatch):
    monkeypatch.setattr(providers, "set_reserve", lambda *a, **k: pytest.fail("no cloud call"))
    out = _run(s, {"kind": "reserve_soc", "mode": "tou", "soc": 20}, dry_run=True)
    assert "dry run" in out.detail
