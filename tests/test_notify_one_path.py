"""#374 P2: every companion push goes through the one Notifier.

The Push notifications switch stops them all (#171), each names its gateway (#361), and
each send is recorded in the ledger, which the Recent notifications list reads.
"""
import time

import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import (alerts, app as app_module, battery_control,
                                              notify_engine, notify, scheduler, state,
                                              vpp_monitor)
from franklinwh_direct_connect_bridge.db import MetricsStore


@pytest.fixture
def st(tmp_path, monkeypatch):
    from franklinwh_direct_connect_bridge import db
    s = MetricsStore(str(tmp_path / "m.db"))
    monkeypatch.setattr(db, "get_store", lambda _s: s)
    s.create_ha_instance(ha_id="ha1", name="Home", base_url="http://ha.test", token="t")
    s.create_notify_device(dev_id="d1", alias="Phone", instance_id="ha1",
                           service="notify.mobile_app_phone")
    gw = state.GatewayState(id="gw-shed", label="Shed", configured_host="h1", active_host="h1")
    monkeypatch.setitem(state._gateways, "gw-shed", gw)
    monkeypatch.setattr(state, "_default_id", "gw-shed")
    vpp_monitor.reset()
    monkeypatch.setattr(battery_control, "current", lambda host=None: {"active": None})
    yield s
    vpp_monitor.reset()


def _ledger(st):
    return st._conn.execute(
        "SELECT direction, event, gateway, message FROM notify_ledger ORDER BY id").fetchall()


# ── #171: the switch stops every companion push ──────────────────────────────────────
def test_switch_off_stops_trigger_notifications(st, fake_notifier):
    sends = fake_notifier(st, on=False)
    assert notify_engine.fire(st, "off_grid", gateway="Shed") == 0
    assert sends == []
    assert _ledger(st)[0][:3] == ("SKIPPED", "off_grid", "Shed")


def test_switch_off_stops_vpp_monitor_notifications(st, fake_notifier):
    sends = fake_notifier(st, on=False)
    vpp_monitor.check("h1", st, snapshot={"vpp": False}, label="Shed")
    vpp_monitor.check("h1", st, snapshot={"vpp": True}, label="Shed")
    assert sends == []
    assert [r[:3] for r in _ledger(st)] == [("SKIPPED", "dispatch_start", "Shed")]


def test_switch_off_stops_scheduler_notify_actions(st, fake_notifier):
    sends = fake_notifier(st, on=False)
    out = scheduler.run_action({"kind": "notify", "device_id": "d1", "title": "T", "message": "M"},
                               settings=None, client=None, store=st, snapshot={},
                               gateway_id="gw-shed")
    assert sends == [] and out == "notify 'Phone': skipped: notifications are off"


def test_switch_off_stops_broadcast_and_the_dialog_says_why(st, fake_notifier):
    sends = fake_notifier(st, on=False)
    r = TestClient(app_module.create_app()).post("/api/ha/notify-devices/broadcast",
                                                 json={"message": "hello"}).json()
    assert sends == [] and r["sent"] == 0 and r["detail"] == "Push notifications are off"


def test_broadcast_with_the_switch_on_reports_each_device(st, fake_notifier):
    sends = fake_notifier(st)
    r = TestClient(app_module.create_app()).post("/api/ha/notify-devices/broadcast",
                                                 json={"title": "T", "message": "hello"}).json()
    assert r == {"sent": 1, "total": 1,
                 "results": [{"device_id": "d1", "alias": "Phone", "ok": True}]}
    assert sends[0]["message"] == "hello"


# ── #361: every message and its record name the gateway ──────────────────────────────
def test_trigger_messages_and_records_name_the_gateway(st, fake_notifier):
    sends = fake_notifier(st)
    assert notify_engine.fire(st, "aGate_offline", gateway="Shed") == 1
    assert "[Shed]" in sends[0]["message"] and sends[0]["targets"] == ["ha1::mobile_app_phone"]
    row = st.notify_log(limit=1)[0]
    assert (row["gateway"], row["device"], row["ok"]) == ("Shed", "Phone", 1)


def test_scheduler_notify_names_the_gateway_by_label(st, fake_notifier):
    sends = fake_notifier(st)
    out = scheduler.run_action({"kind": "notify", "device_id": "d1", "title": "T", "message": "M"},
                               settings=None, client=None, store=st, snapshot={},
                               gateway_id="gw-shed")
    assert out == "notify 'Phone': sent"
    assert sends[0]["title"] == "T" and sends[0]["message"] == "M [Shed]"
    assert _ledger(st)[0][:3] == ("SENT", "schedule_notify", "Shed")


def test_vpp_dispatch_notification_names_the_gateway(st, fake_notifier):
    sends = fake_notifier(st)
    vpp_monitor.check("h1", st, snapshot={"vpp": False}, label="Shed")
    vpp_monitor.check("h1", st, snapshot={"vpp": True}, label="Shed")
    assert sends and sends[0]["message"].startswith("Shed: Battery dispatch STARTED")
    assert _ledger(st)[0][:3] == ("SENT", "dispatch_start", "Shed")


def test_reconcile_notice_carries_its_gateway(monkeypatch):
    class Store:
        def active_dispatches(self, host=None):
            return [dict(id=1, schedule_id="s1", name="Peak", gateway_id="gw-shed",
                         window_end_ts=time.time() + 600, watts=-1000)]
        def end_dispatch(self, *a, **k): pass
        def log_schedule_event(self, *a, **k): pass
    monkeypatch.setattr(battery_control, "status", lambda host: {"vpp_active": False})
    notes = []
    battery_control.reconcile_interrupted(Store(), "h1", "notify",
                                          notify=lambda a, d, g: notes.append((a, g)))
    assert notes == [("notified", "gw-shed")]


def test_persistent_transition_notices_name_the_gateway():
    t = notify.transitions({"ok": True}, {"ok": False}, "Shed")
    assert t and "[Shed]" in t[0][1]


def test_alert_notifications_name_the_gateway_by_label(st):
    msg = alerts._ha_message({"message": "m", "code": "SCHEDULE_FAILED", "gateway_id": "gw-shed"})
    assert "gateway Shed" in msg and "gw-shed" not in msg


# ── the log keeps its history ────────────────────────────────────────────────────────
def test_recent_notifications_keep_rows_from_before_the_ledger(st, fake_notifier):
    st._conn.execute("INSERT INTO notify_log(ts, event, title, message, device, ok) "
                     "VALUES (1, 'off_grid', 'T', 'old', 'Phone', 1)")
    st._conn.commit()
    fake_notifier(st)
    notify_engine.fire(st, "on_grid", gateway="Shed")
    log = st.notify_log()
    assert [r["message"] for r in log][1] == "old" and log[0]["event"] == "on_grid"
    stats = notify_engine.stats_by_trigger(st.notify_stats())
    assert [(s["event"], s["count"], s["delivered"]) for s in stats] == [("off_grid", 2, 2)]


def test_recent_notifications_show_the_gateway():
    from pathlib import Path
    html = (Path(notify_engine.__file__).parent / "templates/tabs/settings.html").read_text()
    row = html[html.index("Recent notifications (delivery log)"):html.index("<!-- Add-on note -->")]
    assert 'data-testid="notify-log-gateway" x-text="e.gateway"' in row
