"""#300: the VPP dispatch lines say what the site was doing, and how long it lasted."""
import pytest

from franklinwh_direct_connect_bridge import battery_control, vpp_monitor


class _Store:
    def __init__(self):
        self.events = []

    def __getattr__(self, name):          # _log_event writes through whatever it calls
        return lambda *a, **k: self.events.append((name, a, k))


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    vpp_monitor.reset()
    monkeypatch.setattr(battery_control, "current", lambda host=None: {"active": None})
    yield
    vpp_monitor.reset()


def _run(snap, clock, monkeypatch):
    monkeypatch.setattr(vpp_monitor.time, "time", lambda: clock)
    return vpp_monitor.check("h", _Store(), notify=False, snapshot=snap)


IDLE = {"vpp": False, "battery_w": 0, "grid_w": 292, "solar_w": 0, "load_w": 292, "soc": 94.0}
DISPATCH = {"vpp": True, "battery_w": 4954, "grid_w": -4729, "solar_w": 0, "load_w": 225,
            "soc": 95.0}


def test_started_and_ended_carry_metrics_and_duration(monkeypatch, caplog):
    caplog.set_level("INFO", logger=vpp_monitor.log.name)
    _run(IDLE, 1000.0, monkeypatch)
    assert _run(DISPATCH, 1010.0, monkeypatch)["event"] == "start"
    assert _run(IDLE, 1064.0, monkeypatch)["event"] == "stop"
    start, end = [r.getMessage() for r in caplog.records][-2:]
    assert "battery 4954 W, grid -4729 W, solar 0 W, load 225 W, SoC 95.0%" in start
    assert "ENDED after 54 s" in end
    assert "battery 0 W, grid 292 W, solar 0 W, load 292 W, SoC 94.0%" in end


def test_a_dispatch_already_running_at_start_has_no_made_up_duration(monkeypatch, caplog):
    caplog.set_level("INFO", logger=vpp_monitor.log.name)
    _run(DISPATCH, 1000.0, monkeypatch)            # first sight: already dispatching
    _run(IDLE, 1300.0, monkeypatch)
    end = caplog.records[-1].getMessage()
    assert end.startswith("Battery dispatch ENDED —"), end


def test_a_missing_value_is_left_out_not_shown_as_zero():
    assert vpp_monitor._metrics({"battery_w": 200, "grid_w": None}) == "battery 200 W"
    assert vpp_monitor._metrics({}) == "no power reading"
