"""The `alerts` table and its delivery outbox (#271, shared spec v1 §1, §7)."""

from franklinwh_direct_connect_bridge.db import MetricsStore

DAY = 86400


def _store(tmp_path):
    return MetricsStore(str(tmp_path / "m.db"))


def _event(st, *, ts=1000.0, code="COMMAND_REFUSED", gw="gw1", sev="critical"):
    return st.insert_alert(gateway_id=gw, kind="event", severity=sev, code=code,
                           title="t", message="m", opened_ts=ts)


def _condition(st, *, ts=1000.0, code="GATEWAY_UNREACHABLE", gw="gw1", sev="critical"):
    return st.insert_alert(gateway_id=gw, kind="condition", severity=sev, code=code,
                           title="t", message="m", opened_ts=ts)


def test_record_has_every_spec_field(tmp_path):
    st = _store(tmp_path)
    aid = _event(st)
    row = st.alert(aid)
    assert set(row) == {"id", "gateway_id", "kind", "severity", "code", "title", "message",
                        "opened_ts", "last_ts", "count", "resolved_ts", "acked_by",
                        "acked_ts"}
    assert row["count"] == 1 and row["last_ts"] == row["opened_ts"] == 1000.0


def test_lifecycle_survives_a_restart(tmp_path):
    """Open, merge, ack, resolve — every step is on disk, so a new process sees it."""
    st = _store(tmp_path)
    e = _event(st)
    c = _condition(st)
    st.merge_alert(e, message="again", now=1100.0)
    st.ack_alert(c, acked_by="source:ui", now=1200.0)
    st.close()

    st2 = _store(tmp_path)
    row = st2.alert(e)
    assert (row["count"], row["last_ts"], row["message"]) == (2, 1100.0, "again")
    assert st2.alert(c)["acked_by"] == "source:ui"
    # An acknowledged condition that is still active stays open (the red bar).
    assert {r["id"] for r in st2.alerts(open_only=True)} == {e, c}
    st2.resolve_alert(c, resolved_ts=1300.0)
    st2.close()

    st3 = _store(tmp_path)
    assert st3.alert(c)["resolved_ts"] == 1300.0
    assert [r["id"] for r in st3.alerts(open_only=True)] == [e]


def test_ack_keeps_the_first_acknowledgement(tmp_path):
    st = _store(tmp_path)
    e = _event(st)
    st.ack_alert(e, acked_by="source:ui", now=1.0)
    row = st.ack_alert(e, acked_by="source:api", now=2.0)
    assert (row["acked_by"], row["acked_ts"]) == ("source:ui", 1.0)
    assert st.ack_alert(999, acked_by="source:ui", now=1.0) is None


def test_resolved_but_unacknowledged_condition_is_still_open(tmp_path):
    """A fault that came and went while nobody was looking still owes the modal."""
    st = _store(tmp_path)
    c = _condition(st)
    st.resolve_alert(c, resolved_ts=2000.0)
    assert [r["id"] for r in st.alerts(open_only=True)] == [c]


def test_open_condition_is_per_gateway_and_code(tmp_path):
    st = _store(tmp_path)
    a = _condition(st, gw="gw1")
    _condition(st, gw="gw2")
    assert st.open_condition("gw1", "GATEWAY_UNREACHABLE")["id"] == a
    assert st.open_condition("gw1", "MQTT_DOWN") is None
    st.resolve_alert(a, resolved_ts=5.0)
    assert st.open_condition("gw1", "GATEWAY_UNREACHABLE") is None


def test_filters(tmp_path):
    st = _store(tmp_path)
    e = _event(st, ts=100.0)
    c = _condition(st, ts=200.0)
    assert [r["id"] for r in st.alerts()] == [c, e]            # newest first
    assert [r["id"] for r in st.alerts(kind="event")] == [e]
    assert [r["id"] for r in st.alerts(since=150.0)] == [c]
    assert [r["id"] for r in st.alerts(gateway_id="nope")] == []


def test_summary_levels(tmp_path):
    st = _store(tmp_path)
    assert st.alert_summary() == {"level": "ok", "open": 0, "latest_id": None,
                                  "changed_ts": None}
    w = _event(st, code="INTERNAL_ERROR", sev="warning")
    assert st.alert_summary() == {"level": "warning", "open": 1, "latest_id": w,
                                  "changed_ts": 1000.0}
    c = _event(st)
    assert st.alert_summary() == {"level": "critical", "open": 2, "latest_id": c,
                                  "changed_ts": 1000.0}
    st.ack_alert(c, acked_by="source:ui", now=1500.0)
    assert st.alert_summary()["level"] == "warning"
    assert st.alert_summary()["changed_ts"] == 1500.0


def test_changed_ts_sees_a_condition_resolve_while_unacknowledged(tmp_path):
    """open and latest_id stay the same; changed_ts is what tells the UI to refetch."""
    st = _store(tmp_path)
    c = _condition(st, ts=1000.0)
    before = st.alert_summary()
    st.resolve_alert(c, resolved_ts=2000.0)
    after = st.alert_summary()
    assert (before["open"], before["latest_id"]) == (after["open"], after["latest_id"])
    assert (before["changed_ts"], after["changed_ts"]) == (1000.0, 2000.0)


def test_prune_keeps_open_alerts_however_old(tmp_path):
    st = _store(tmp_path)
    now = 200 * DAY
    old_open_event = _event(st, ts=1.0)
    old_active = _condition(st, ts=1.0)
    st.ack_alert(old_active, acked_by="source:ui", now=2.0)       # acked, still active
    old_resolved_unacked = _condition(st, ts=1.0, code="LIVE_DATA_MISSING")
    st.resolve_alert(old_resolved_unacked, resolved_ts=2.0)
    old_closed = _event(st, ts=1.0, code="SCHEDULE_FAILED")
    st.ack_alert(old_closed, acked_by="source:ui", now=2.0)
    st.queue_delivery(old_closed, "ha_persistent")
    recent_closed = _event(st, ts=now - DAY, code="WRITE_IGNORED")
    st.ack_alert(recent_closed, acked_by="source:ui", now=now - DAY)

    assert st.prune_alerts(now=now) == 1
    left = {r["id"] for r in st.alerts()}
    assert left == {old_open_event, old_active, old_resolved_unacked, recent_closed}
    assert st.alert_deliveries(old_closed) == []


def test_prune_dates_a_condition_by_its_later_close(tmp_path):
    """Acked long ago but resolved recently: kept until 90 days after the resolve."""
    st = _store(tmp_path)
    now = 200 * DAY
    c = _condition(st, ts=1.0)
    st.ack_alert(c, acked_by="source:ui", now=2.0)
    st.resolve_alert(c, resolved_ts=now - 10 * DAY)
    assert st.prune_alerts(now=now) == 0
    assert st.prune_alerts(now=now + 81 * DAY) == 1


def test_delivery_outbox(tmp_path):
    st = _store(tmp_path)
    a = _event(st)
    st.queue_delivery(a, "ha_persistent")
    st.queue_delivery(a, "ha_persistent")                          # idempotent
    assert [d["channel"] for d in st.pending_deliveries()] == ["ha_persistent"]
    st.record_delivery(a, "ha_persistent", ok=False, error="timed out", now=5.0)
    d = st.alert_deliveries(a)[0]
    assert (d["attempts"], d["delivered_ts"], d["last_error"]) == (1, None, "timed out")
    assert st.pending_deliveries()                                 # still owed
    st.record_delivery(a, "ha_persistent", ok=True, now=6.0)
    d = st.alert_deliveries(a)[0]
    assert (d["attempts"], d["delivered_ts"], d["last_error"]) == (2, 6.0, None)
    assert st.pending_deliveries() == []


def test_skipped_delivery_is_recorded_not_retried(tmp_path):
    st = _store(tmp_path)
    a = _event(st)
    st.queue_delivery(a, "ha_persistent")
    st.record_delivery(a, "ha_persistent", ok=False, attempted=False,
                       error="skipped: no Home Assistant API configured")
    assert st.pending_deliveries() == []
    assert st.alert_deliveries(a)[0]["attempts"] == 0


def test_migration_is_idempotent_on_an_existing_db(tmp_path):
    st = _store(tmp_path)
    a = _event(st)
    st.close()
    st2 = _store(tmp_path)          # runs every migration again over the same file
    assert st2.alert(a)["code"] == "COMMAND_REFUSED"
