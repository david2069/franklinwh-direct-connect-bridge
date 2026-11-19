"""#160: a scheduled force runs until its window closes. Its auto-release came from the
schedule's duration_min (hidden for Recurring windows, 90 by default), so a force in a
3-hour window was released after 90 minutes."""
import time

import pytest

from franklinwh_direct_connect_bridge import battery_control
from franklinwh_direct_connect_bridge import scheduler as SCH


@pytest.fixture
def sent(monkeypatch):
    calls = []

    def execute(cmd, **kw):
        calls.append(kw)
        return {"ok": True, "result": "sent"}
    monkeypatch.setattr(battery_control, "execute", execute)
    return calls


def _force(window_min, window_end_ts):
    return SCH._force_dispatch({"direction": "charge", "power": 50}, host="10.0.0.1",
                               window_min=window_min, gateway_id="gw1", store=None,
                               window_end_ts=window_end_ts)


def test_a_force_in_a_three_hour_window_runs_until_it_closes(sent):
    _force(90, time.time() + 3 * 3600)
    assert abs(sent[0]["duration_s"] - 3 * 3600) <= 5


def test_a_force_started_late_in_its_window_ends_at_the_close(sent):
    _force(60, time.time() + 600)
    assert abs(sent[0]["duration_s"] - 600) <= 5


def test_with_no_window_end_the_duration_is_used(sent):
    _force(30, None)
    assert sent[0]["duration_s"] == 1800


def test_a_past_window_end_falls_back_to_the_duration(sent):
    _force(30, time.time() - 60)
    assert sent[0]["duration_s"] == 1800
