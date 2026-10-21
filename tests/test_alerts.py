"""The alert lifecycle (#271, shared spec v1 §2, §3, §6): thresholds, dedup, ack, outbox."""

import logging
from pathlib import Path

import pytest

from franklinwh_direct_connect_bridge import alerts, workers
from franklinwh_direct_connect_bridge.db import MetricsStore
from franklinwh_direct_connect_bridge.notify import Notifier


@pytest.fixture(autouse=True)
def _fresh():
    alerts.reset()
    yield
    alerts.reset()


@pytest.fixture
def st(tmp_path):
    s = MetricsStore(str(tmp_path / "m.db"))
    yield s
    s.close()


class FakeNotifier:
    def __init__(self, *errors):
        self.errors = list(errors)
        self.calls = []

    def call_service(self, domain, service, data):
        self.calls.append((domain, service, data))
        return self.errors.pop(0) if self.errors else ""


# ── condition thresholds ──────────────────────────────────────────────────────
@pytest.mark.parametrize("code,open_s,resolve_s", [
    ("GATEWAY_UNREACHABLE", 300, 120),
    ("LIVE_DATA_MISSING", 120, 60),
    ("MQTT_DOWN", 300, 120),
    ("HA_UNREACHABLE", 300, 120),
])
def test_condition_opens_and_resolves_at_its_boundary(st, code, open_s, resolve_s):
    t0 = 10_000.0
    alerts.set_condition("gw1", code, True, now=t0)
    alerts.set_condition("gw1", code, True, now=t0 + open_s - 1)
    assert alerts.evaluate(st, now=t0 + open_s - 1) == []
    ch = alerts.evaluate(st, now=t0 + open_s)
    assert [c["change"] for c in ch] == ["opened"]
    row = st.alert(ch[0]["id"])
    assert row["opened_ts"] == t0                       # dated from when it began
    assert (row["kind"], row["code"], row["gateway_id"]) == ("condition", code, "gw1")

    t1 = t0 + open_s + 30
    alerts.set_condition("gw1", code, False, now=t1)
    assert alerts.evaluate(st, now=t1 + resolve_s - 1) == []
    ch = alerts.evaluate(st, now=t1 + resolve_s)
    assert [c["change"] for c in ch] == ["resolved"]
    assert st.alert(row["id"])["resolved_ts"] == t1     # dated from when it cleared


def test_a_blip_does_not_open_and_flapping_restarts_the_clock(st):
    alerts.set_condition("gw1", "GATEWAY_UNREACHABLE", True, now=0.0)
    alerts.set_condition("gw1", "GATEWAY_UNREACHABLE", False, now=200.0)
    alerts.set_condition("gw1", "GATEWAY_UNREACHABLE", True, now=210.0)
    assert alerts.evaluate(st, now=400.0) == []           # 190 s of the new run
    assert alerts.evaluate(st, now=510.0)[0]["change"] == "opened"


def test_a_short_recovery_does_not_resolve(st):
    alerts.set_condition("gw1", "GATEWAY_UNREACHABLE", True, now=0.0)
    alerts.evaluate(st, now=300.0)
    alerts.set_condition("gw1", "GATEWAY_UNREACHABLE", False, now=400.0)
    alerts.set_condition("gw1", "GATEWAY_UNREACHABLE", True, now=450.0)
    assert alerts.evaluate(st, now=600.0) == []
    assert st.open_condition("gw1", "GATEWAY_UNREACHABLE")["last_ts"] == 600.0


def test_one_open_condition_per_gateway_and_code(st):
    alerts.set_condition("gw1", "GATEWAY_UNREACHABLE", True, now=0.0)
    alerts.set_condition("gw2", "GATEWAY_UNREACHABLE", True, now=0.0)
    for t in (300.0, 315.0, 330.0, 900.0):
        alerts.evaluate(st, now=t)
    rows = st.alerts(kind="condition")
    assert sorted(r["gateway_id"] for r in rows) == ["gw1", "gw2"]


def test_set_condition_ignores_events_and_unknown_codes():
    alerts.set_condition("gw1", "COMMAND_REFUSED", True)
    alerts.set_condition("gw1", "NOT_A_CODE", True)
    assert alerts.facts() == {}


# ── events ────────────────────────────────────────────────────────────────────
def test_events_within_ten_minutes_merge(st):
    a = alerts.raise_event(st, "gw1", "COMMAND_REFUSED", "first", now=1000.0)
    b = alerts.raise_event(st, "gw1", "COMMAND_REFUSED", "second", now=1000.0 + 600)
    assert a == b
    row = st.alert(a)
    assert (row["count"], row["last_ts"], row["message"]) == (2, 1600.0, "second")
    # The window runs from the LAST repeat, and it is per gateway and per code.
    assert alerts.raise_event(st, "gw1", "COMMAND_REFUSED", "x", now=2200.0) == a
    assert alerts.raise_event(st, "gw2", "COMMAND_REFUSED", "x", now=2200.0) != a
    assert alerts.raise_event(st, "gw1", "SCHEDULE_FAILED", "x", now=2200.0) != a
    assert alerts.raise_event(st, "gw1", "COMMAND_REFUSED", "x", now=2801.0) != a


def test_an_acknowledged_event_is_not_merged_into(st):
    a = alerts.raise_event(st, "gw1", "COMMAND_REFUSED", "first", now=1000.0)
    alerts.ack(st, a, "ui", now=1001.0)
    assert alerts.raise_event(st, "gw1", "COMMAND_REFUSED", "again", now=1002.0) != a


def test_internal_error_is_rate_limited_to_one_an_hour(st):
    a = alerts.raise_event(st, "", "INTERNAL_ERROR", "boom", now=0.0)
    alerts.ack(st, a, "ui", now=1.0)
    assert alerts.raise_event(st, "", "INTERNAL_ERROR", "boom", now=3599.0) == a
    assert st.alert(a)["count"] == 2
    assert alerts.raise_event(st, "", "INTERNAL_ERROR", "boom", now=3600.0) != a


def test_raise_event_rejects_a_condition_code_without_raising(st):
    assert alerts.raise_event(st, "gw1", "GATEWAY_UNREACHABLE", "x") is None
    assert alerts.raise_event(None, "gw1", "COMMAND_REFUSED", "x") is None
    assert st.alerts() == []


def test_only_critical_alerts_queue_a_home_assistant_notification(st):
    c = alerts.raise_event(st, "gw1", "COMMAND_REFUSED", "x", now=1.0)
    w = alerts.raise_event(st, "gw1", "EXTERNAL_SETPOINT", "x", now=1.0)
    alerts.raise_event(st, "gw1", "COMMAND_REFUSED", "repeat", now=2.0)   # merge
    assert [(d["alert_id"], d["channel"]) for d in st.pending_deliveries()] == \
        [(c, alerts.CH_HA_CREATE)]
    assert st.alert(w)["severity"] == "warning"


# ── logging (addendum: every alert is a line in the app log) ──────────────────
def test_every_raise_resolve_and_ack_is_logged(st, caplog):
    caplog.set_level(logging.INFO, logger="franklinwh_direct_connect_bridge.alerts")
    a = alerts.raise_event(st, "gw1", "COMMAND_REFUSED", "Force rejected", now=1.0)
    alerts.raise_event(st, "gw1", "COMMAND_REFUSED", "Force rejected", now=2.0)
    alerts.ack(st, a, "api", now=3.0)
    alerts.set_condition("gw1", "LIVE_DATA_MISSING", True, now=0.0)
    alerts.evaluate(st, now=120.0)
    alerts.set_condition("gw1", "LIVE_DATA_MISSING", False, now=130.0)
    alerts.evaluate(st, now=190.0)
    recs = [(r.levelname, r.getMessage()) for r in caplog.records]
    assert sum(1 for lv, m in recs if lv == "WARNING" and "COMMAND_REFUSED" in m) == 2
    assert any(lv == "INFO" and "acknowledged by source:api" in m for lv, m in recs)
    assert any(lv == "WARNING" and "LIVE_DATA_MISSING" in m for lv, m in recs)
    assert any(lv == "INFO" and "LIVE_DATA_MISSING" in m and "resolved" in m
               for lv, m in recs)


# ── acknowledgement ───────────────────────────────────────────────────────────
def test_ack_records_the_source_and_rejects_others(st):
    a = alerts.raise_event(st, "gw1", "COMMAND_REFUSED", "x", now=1.0)
    with pytest.raises(ValueError):
        alerts.ack(st, a, "user:david")
    row = alerts.ack(st, a, "ui", now=5.0)
    assert (row["acked_by"], row["acked_ts"]) == ("source:ui", 5.0)
    assert alerts.ack(st, 999, "ui") is None


def test_ack_of_a_condition_keeps_it_active(st):
    alerts.set_condition("gw1", "GATEWAY_UNREACHABLE", True, now=0.0)
    aid = alerts.evaluate(st, now=300.0)[0]["id"]
    alerts.ack(st, aid, "ui", now=301.0)
    assert st.alert(aid)["resolved_ts"] is None
    assert [r["id"] for r in st.alerts(open_only=True)] == [aid]
    assert alerts.evaluate(st, now=400.0) == []           # no second alert either


# ── the outbox ────────────────────────────────────────────────────────────────
def test_delivery_creates_then_ack_dismisses(st):
    n = FakeNotifier()
    a = alerts.raise_event(st, "gw1", "COMMAND_REFUSED", "Force rejected", now=1.0)
    assert alerts.deliver(st, n, now=2.0) == 1
    dom, svc, data = n.calls[0]
    assert (dom, svc, data["notification_id"]) == \
        ("persistent_notification", "create", f"fwh_dc_alert_{a}")
    assert "Force rejected" in data["message"]
    alerts.ack(st, a, "ui", now=3.0)
    assert alerts.deliver(st, n, now=4.0) == 1
    assert n.calls[1][1:] == ("dismiss", {"notification_id": f"fwh_dc_alert_{a}"})
    assert st.pending_deliveries() == []


def test_failed_delivery_retries_with_back_off_and_never_loses_the_alert(st):
    n = FakeNotifier("connection refused", "connection refused")
    a = alerts.raise_event(st, "gw1", "COMMAND_REFUSED", "x", now=0.0)
    assert alerts.deliver(st, n, now=0.0) == 0
    assert alerts.deliver(st, n, now=14.0) == 0 and len(n.calls) == 1   # backing off
    assert alerts.deliver(st, n, now=15.0) == 0 and len(n.calls) == 2
    assert alerts.deliver(st, n, now=44.0) == 0 and len(n.calls) == 2   # 30 s now
    assert alerts.deliver(st, n, now=45.0) == 1
    d = st.alert_deliveries(a)[0]
    assert d["attempts"] == 3 and d["delivered_ts"] == 45.0 and d["last_error"] is None
    assert st.alert(a)["acked_ts"] is None                # the alert itself is untouched


def test_failed_delivery_feeds_ha_unreachable(st):
    alerts.raise_event(st, "gw1", "COMMAND_REFUSED", "x", now=0.0)
    alerts.deliver(st, FakeNotifier("timed out"), now=0.0)
    assert alerts.facts()[("", "HA_UNREACHABLE")]["bad"] is True
    alerts.deliver(st, FakeNotifier(), now=20.0)
    assert alerts.facts()[("", "HA_UNREACHABLE")]["bad"] is False


def test_no_home_assistant_is_recorded_as_skipped(st):
    a = alerts.raise_event(st, "gw1", "COMMAND_REFUSED", "x", now=0.0)
    alerts.deliver(st, FakeNotifier("skipped: no Home Assistant API configured"), now=0.0)
    d = st.alert_deliveries(a)[0]
    assert d["last_error"].startswith("skipped:") and d["attempts"] == 0
    assert st.pending_deliveries() == []
    assert ("", "HA_UNREACHABLE") not in alerts.facts()   # not configured is not down


def test_acknowledged_before_delivery_is_not_sent(st):
    n = FakeNotifier("refused")
    a = alerts.raise_event(st, "gw1", "COMMAND_REFUSED", "x", now=0.0)
    alerts.deliver(st, n, now=0.0)                        # first attempt fails
    alerts.ack(st, a, "ui", now=1.0)
    alerts.deliver(st, n, now=100.0)
    assert len(n.calls) == 1                              # neither create nor dismiss
    assert st.pending_deliveries() == []


def test_notifier_without_a_target_skips(monkeypatch):
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)

    class S:
        ha_notify, ha_url, ha_token = True, "", ""
    assert Notifier(S()).call_service("persistent_notification", "create", {}) \
        .startswith("skipped:")

    class Off:
        ha_notify, ha_url, ha_token = False, "http://192.0.2.1:8123", "t"
    assert Notifier(Off()).call_service("persistent_notification", "create", {}) == \
        "skipped: HA channel off"


def test_ha_channel_off_is_recorded_exactly_and_the_alert_stays_open(st, monkeypatch):
    """Owner decision (modbus-bridge #324): ha_notify off skips HA, never the bridge."""
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)

    class Off:
        ha_notify, ha_url, ha_token = False, "http://192.0.2.1:8123", "t"
    a = alerts.raise_event(st, "gw1", "COMMAND_REFUSED", "x", now=0.0)
    alerts.deliver(st, Notifier(Off()), now=0.0)            # no network: skipped first
    d = st.alert_deliveries(a)[0]
    assert d["last_error"] == "skipped: HA channel off" and d["attempts"] == 0
    assert st.pending_deliveries() == []
    # The modal's set: critical and unacknowledged, whatever ha_notify says.
    assert [(r["id"], r["severity"], r["acked_ts"]) for r in st.alerts(open_only=True)] == \
        [(a, "critical", None)]


# ── WORKER_STALLED ────────────────────────────────────────────────────────────
def _worker(name="poller:gw1", scope="gateway:gw1"):
    return workers.Worker(name=name, concern="t", cadence_s=5.0, scope=scope)


def test_worker_stalled_opens_from_the_supervisor_and_resolves_on_recovery(st):
    reg = workers.Registry()
    w = reg.register(_worker())
    w.state = workers.WorkerState.UNRESPONSIVE
    alerts.on_worker_transition(w, "no heartbeat for 40s", now=100.0)
    alerts.check_workers(reg, now=100.0)                  # still broken: stays bad
    ch = alerts.evaluate(st, now=100.0)
    assert [(c["code"], c["gateway_id"], c["change"]) for c in ch] == \
        [("WORKER_STALLED", "gw1", "opened")]
    assert "poller:gw1" in st.alert(ch[0]["id"])["message"]
    assert st.alert(ch[0]["id"])["severity"] == "critical"

    w.beat(state=workers.WorkerState.RUNNING)
    alerts.check_workers(reg, now=130.0)
    assert alerts.evaluate(st, now=130.0)[0]["change"] == "resolved"


def test_worker_transitions_that_are_not_stalls_are_ignored():
    w = _worker(scope="global")
    w.state = workers.WorkerState.STOPPED
    alerts.on_worker_transition(w, "stopped")
    assert alerts.facts() == {}


# ── the monitor ───────────────────────────────────────────────────────────────
def test_monitor_pass_evaluates_delivers_and_prunes(st):
    n = FakeNotifier()
    reg = workers.Registry()
    mon = alerts.AlertMonitor(None, store_fn=lambda: st, notifier=n, registry=reg)
    old = st.insert_alert(gateway_id="", kind="event", severity="warning",
                          code="INTERNAL_ERROR", title="t", message="m", opened_ts=1.0)
    st.ack_alert(old, acked_by="source:ui", now=2.0)
    alerts.set_condition("gw1", "GATEWAY_UNREACHABLE", True, now=0.0)
    now = 100 * 86400.0
    mon.run_once(now=now)
    assert st.alert(old) is None                          # pruned
    cur = st.open_condition("gw1", "GATEWAY_UNREACHABLE")
    assert cur is not None
    assert n.calls and n.calls[0][2]["notification_id"] == f"fwh_dc_alert_{cur['id']}"


def test_monitor_status_reports_absence_as_data():
    assert alerts.monitor_status(workers.Registry())["state"] == "absent"


# -- G1 findings, 2026-10-21 --------------------------------------------------------

def test_removing_a_gateway_resolves_its_open_conditions(tmp_path):
    from franklinwh_direct_connect_bridge import db
    from franklinwh_direct_connect_bridge.config import get_settings
    store = db.get_store(get_settings())
    alerts.reset()
    alerts.set_condition("gw1", "GATEWAY_UNREACHABLE", True, now=0)
    alerts.evaluate(store, now=10_000)
    assert store.open_condition("gw1", "GATEWAY_UNREACHABLE") is not None
    assert alerts.forget_gateway(store, "gw1", now=10_001)
    assert store.open_condition("gw1", "GATEWAY_UNREACHABLE") is None
    assert not [k for k in alerts.facts() if k[0] == "gw1"]


def test_an_unreachable_gateway_is_not_also_live_data_missing():
    src = (Path(alerts.__file__).parent / "poller.py").read_text()
    assert '"LIVE_DATA_MISSING", outcome == "ok" and not summ.get("power")' in src
