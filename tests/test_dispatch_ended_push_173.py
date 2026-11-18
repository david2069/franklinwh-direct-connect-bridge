"""#173: the "Battery dispatch (VPP / force) started / ended" trigger sends "ended" too, and
fires for this bridge's own dispatches as well as external ones."""
import pytest

from franklinwh_direct_connect_bridge import battery_control, notify_engine, vpp_monitor


class _Store:
    def __getattr__(self, name):
        return lambda *a, **k: None


@pytest.fixture
def sent(monkeypatch):
    vpp_monitor.reset()
    out = []
    monkeypatch.setattr(notify_engine, "fire",
                        lambda store, event, **kw: out.append((event, kw)) or 1)
    yield out
    vpp_monitor.reset()


def _run(snap, clock, monkeypatch, active=None):
    monkeypatch.setattr(battery_control, "current", lambda host=None: {"active": active})
    monkeypatch.setattr(vpp_monitor.time, "time", lambda: clock)
    return vpp_monitor.check("h", _Store(), notify=True, snapshot=snap, label="Home")


IDLE = {"vpp": False, "battery_w": 0, "grid_w": 292, "solar_w": 0, "load_w": 292, "soc": 94.0}
ON = {"vpp": True, "battery_w": 4954, "grid_w": -4729, "solar_w": 0, "load_w": 225, "soc": 95.0}


def test_an_external_dispatch_sends_started_and_ended(sent, monkeypatch):
    _run(IDLE, 1000.0, monkeypatch)
    _run(ON, 1010.0, monkeypatch)
    _run(IDLE, 1064.0, monkeypatch)
    assert [e for e, _ in sent] == ["dispatch_start", "dispatch_end"]
    end = sent[1][1]
    assert end["gateway"] == "Home" and end["took"] == " after 54 s"
    assert "battery 0 W" in end["metrics"]


def test_this_bridges_own_force_is_notified_too(sent, monkeypatch):
    _run(IDLE, 1000.0, monkeypatch)
    _run(ON, 1010.0, monkeypatch, active="Charge")
    _run(IDLE, 1070.0, monkeypatch)
    assert [e for e, _ in sent] == ["dispatch_start", "dispatch_end"]
    assert sent[0][1]["source"] == "this bridge"


def test_ended_is_the_dispatch_trigger_and_has_a_default_text():
    assert notify_engine.TRIGGER["dispatch_end"] == "dispatch"
    ev = {e.key: e for e in notify_engine.EVENTS}["dispatch_end"]
    assert "ENDED" in ev.message
