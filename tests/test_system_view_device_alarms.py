"""System view → Alarms from the devices (owner, 2026-11-11: "Merge, add device later").

Three sources, each read on its own slow cadence and none guessed:
- the FranklinWH cloud's active gateway alarms (franklinwh-cloud ``get_gateway_alarm()``,
  "Active gateway alarms"), read with the cloud status pass when the bridge is signed in;
- each aPower's ``alarmLevel`` from 1705 battery_cells (0 = none: franklinwh-direct-connect-api
  bms.py prints 0 as "0 (none)" and any other value as an alarm);
- the aGate's 1829 event_block, which gives only ``num`` (the entries can't be read yet).
"""
import time

import pytest

from franklinwh_direct_connect_bridge import client, cloud_status, poller, state, system_view
from franklinwh_direct_connect_bridge.db import MetricsStore

from test_system_view_428 import gw, us_summary


@pytest.fixture(autouse=True)
def _clean():
    state.reset_gateways()
    yield
    state.reset_gateways()


# ── the overlay's alarms ──────────────────────────────────────────────────────
def test_cloud_alarms_show_on_the_agate_while_fresh():
    g = gw(summary=us_summary())
    g.cloud_alarms, g.cloud_alarms_ts = [{"id": 7}, {"id": 8}], time.time()
    al = system_view.gateway_payload(g)["alarms"]
    assert al == [{"target": "agate", "level": "warn",
                   "text": "2 active alarms in the FranklinWH app"}]


def test_stale_or_empty_cloud_alarms_are_left_out():
    g = gw(summary=us_summary())
    g.cloud_alarms, g.cloud_alarms_ts = [{"id": 7}], time.time() - cloud_status.STALE_AFTER_S - 1
    assert "alarms" not in system_view.gateway_payload(g)
    g.cloud_alarms, g.cloud_alarms_ts = [], time.time()
    assert "alarms" not in system_view.gateway_payload(g)


def test_an_apower_alarm_level_shows_on_that_battery():
    g = gw(summary=us_summary())
    g.apower_alarms, g.device_alarms_ts = {1: 0, 2: 3}, time.time()
    assert system_view.gateway_payload(g)["alarms"] == [
        {"target": "battery", "unit": 2, "level": "warn", "text": "aPower 2: alarm level 3"}]


def test_stored_gateway_events_show_as_a_count():
    g = gw(summary=us_summary())
    g.agate_events, g.device_alarms_ts = 2, time.time()
    assert system_view.gateway_payload(g)["alarms"] == [
        {"target": "agate", "level": "warn",
         "text": "2 events in the aGate's log (their details can't be read locally)"}]
    g.agate_events = 0
    assert "alarms" not in system_view.gateway_payload(g)


def test_device_alarms_join_the_bridge_alerts(tmp_path):
    st = MetricsStore(str(tmp_path / "m.db"))
    st.insert_alert(gateway_id="gw1", kind="condition", severity="critical",
                    code="GATEWAY_UNREACHABLE", title="aGate unreachable", message=None,
                    opened_ts=100.0)
    g = gw(summary=us_summary())
    g.apower_alarms, g.device_alarms_ts = {1: 1}, time.time()
    al = system_view.gateway_payload(g, store=st)["alarms"]
    assert [a["text"] for a in al] == ["aPower 1: alarm level 1", "aGate unreachable"]


def test_the_payload_still_validates():
    import franklinwh_system_view as sv
    g = gw(summary=us_summary())
    g.cloud_alarms, g.cloud_alarms_ts = [{"id": 1}], time.time()
    g.apower_alarms, g.agate_events, g.device_alarms_ts = {1: 2}, 1, time.time()
    sv.build({"version": 1, "gateways": [system_view.gateway_payload(g)]})


# ── the reads ────────────────────────────────────────────────────────────────
class _Dev:
    def __init__(self, levels, events):
        self.levels, self.events, self.calls = levels, events, []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def login(self):
        self.calls.append("login")

    def device_ids(self):
        return sorted(self.levels)

    def battery_cells(self, dev_id=1):
        self.calls.append(("cells", dev_id))
        return {"alarmLevel": self.levels[dev_id], "batVolt": [3200] * 16}

    def event_block(self):
        self.calls.append("events")
        return {"num": self.events}


def test_one_session_reads_every_apower_and_the_event_count(monkeypatch):
    dev = _Dev({1: 0, 2: 4}, 3)
    monkeypatch.setattr(client, "_client", lambda s, host=None: dev)
    out = client.device_alarms(None, "h", events=True)
    assert out == {"apower": {1: 0, 2: 4}, "events": 3}
    assert dev.calls == ["login", ("cells", 1), ("cells", 2), "events"]
    dev.calls.clear()
    assert client.device_alarms(None, "h", events=False) == {"apower": {1: 0, 2: 4}}
    assert "events" not in dev.calls


def test_slow_cadences():
    """The aGate is sensitive to load (#123): never every poll."""
    assert poller.APOWER_ALARM_EVERY_S == 300
    assert poller.EVENTS_EVERY_S == 900


def test_the_cloud_pass_reads_the_active_alarms(monkeypatch):
    seen = {}

    class _Cloud:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get_stats(self):
            return type("S", (), {"current": object()})()

        async def get_programme_info(self):
            return []

        def get_metrics(self):
            return {}

        async def get_gateway_alarm(self):
            seen["asked"] = True
            return [{"id": 5}]

    async def _client_for(*a, **k):
        return _Cloud()

    monkeypatch.setattr(cloud_status, "_client_for", _client_for)
    cur, prog, edge, alarms = cloud_status._read_sync("a@example.com", "pw", None)
    assert seen["asked"] and alarms == [{"id": 5}]


def test_a_failed_alarm_read_is_none_not_empty(monkeypatch):
    class _Cloud:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get_stats(self):
            return type("S", (), {"current": object()})()

        async def get_programme_info(self):
            return []

        def get_metrics(self):
            return {}

        async def get_gateway_alarm(self):
            raise RuntimeError("boom")

    async def _client_for(*a, **k):
        return _Cloud()

    monkeypatch.setattr(cloud_status, "_client_for", _client_for)
    assert cloud_status._read_sync("a@example.com", "pw", None)[3] is None
