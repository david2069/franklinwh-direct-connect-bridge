"""Waiting questions with buttons survive a bridge restart (franklinwh-ha-notify#6, 0.1.2).

The Notifier keeps its requests in the bridge database (``Requests.persistent``), so a
tap inside the TTL after a restart still reaches its handler, and a schedule still
holding for its Ask finds its question again. Home Assistant is faked at the package's
send(); a "restart" is a second Notifier built on the same database.
"""
import asyncio
import datetime as dt
import sqlite3
import threading
import time
import types

import pytest
from franklinwh_ha_notify import NO, YES, Button
from franklinwh_ha_notify import notifier as pkg_notifier
from franklinwh_ha_notify.listener import Tap
from franklinwh_ha_notify.send import Delivery, SendResult

from franklinwh_direct_connect_bridge import actionable, alerts
from franklinwh_direct_connect_bridge import battery_control as bc
from franklinwh_direct_connect_bridge import db, notify_buttons
from franklinwh_direct_connect_bridge import scheduler as sch

SETTINGS = types.SimpleNamespace(ha_notify=True)
NOW = dt.datetime(2026, 11, 3, 18, 10, tzinfo=dt.timezone(dt.timedelta(hours=10)))
ASK = {"question": "Charge now?", "timeout_min": 5, "if_no_reply": "skip"}

#: franklinwh-ha-notify 0.1.1's SCHEMA (SCHEMA_VERSION 1): the ledger only.
SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS notify_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL, direction TEXT NOT NULL, event TEXT NOT NULL, gateway TEXT,
    request_id TEXT, status TEXT, title TEXT, message TEXT, delivered INTEGER,
    total INTEGER, detail TEXT);
CREATE INDEX IF NOT EXISTS notify_ledger_ts ON notify_ledger (ts);
"""


@pytest.fixture
def store(tmp_path):
    st = db.MetricsStore(str(tmp_path / "bridge.db"))
    st.create_ha_instance(ha_id="home", name="Home", base_url="http://ha.test:8123",
                          token="t1", is_default=True)
    st.create_notify_device(dev_id="p1", alias="Phone", instance_id="home",
                            service="notify.mobile_app_phone", enabled=True)
    yield st
    st.close()


@pytest.fixture
def sent(monkeypatch):
    out = []

    async def fake_send(instances, targets, title, message, buttons=None, request_id=None):
        out.append({"request_id": request_id, "verbs": [b.verb for b in buttons or []]})
        return SendResult([Delivery(t.key, True) for t in targets])
    monkeypatch.setattr(pkg_notifier, "send", fake_send)
    return out


def _received(store, request_id):
    return [r[0] for r in store._conn.execute(
        "SELECT status FROM notify_ledger WHERE direction='RECEIVED' AND request_id=?",
        (request_id,))]


# ── the schema ────────────────────────────────────────────────────────────────
def test_a_v1_database_gains_the_requests_table(tmp_path):
    path = str(tmp_path / "old.db")
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA_V1)
    conn.execute("INSERT INTO notify_ledger (ts, direction, event) VALUES (1, 'SENT', 'x')")
    conn.commit()
    conn.close()
    st = db.MetricsStore(path)
    try:
        tables = {r[0] for r in st._conn.execute("SELECT name FROM sqlite_master")}
        assert {"notify_ledger", "notify_requests"} <= tables
        assert st._conn.execute("SELECT COUNT(*) FROM notify_ledger").fetchone()[0] == 1
    finally:
        st.close()


def test_the_notifier_keeps_its_requests_in_the_bridge_database(store, sent):
    n = actionable.build(store, SETTINGS)
    req = asyncio.run(n.ask(notify_buttons.TEST, actionable.targets(store),
                            notify_buttons.yes_no(), ttl_s=120))
    assert store._conn.execute("SELECT id FROM notify_requests").fetchall() == [(req.id,)]


# ── Release / Keep and Acknowledge after a restart ────────────────────────────
def _ask_then_restart(store, event, buttons, ttl_s, meta, verb):
    """Ask on one Notifier, then tap the answer on a second built on the same database."""
    before = actionable.build(store, SETTINGS)
    req = asyncio.run(before.ask(event, actionable.targets(store), buttons, ttl_s=ttl_s,
                                 meta=meta, title="t", message="m"))
    after = actionable.build(store, SETTINGS)
    assert {notify_buttons.FORCE_RUNNING, notify_buttons.ALERT} <= set(after._handlers)
    return req, asyncio.run(after.on_tap(Tap("home", verb, req.id, None, {})))


RELEASE_BUTTONS = [Button(notify_buttons.RELEASE, "Release"), Button(NO, "Keep")]


def test_release_tapped_after_a_restart_releases(store, sent, monkeypatch):
    calls = []
    monkeypatch.setattr(notify_buttons, "_store", lambda: store)
    monkeypatch.setattr(bc, "status", lambda host: {"available": True, "vpp_active": True})
    monkeypatch.setattr(bc, "execute", lambda cmd, **kw: calls.append((cmd, kw)) or
                        {"ok": True, "result": "released"})
    req, out = _ask_then_restart(store, notify_buttons.FORCE_RUNNING, RELEASE_BUTTONS, 900,
                                 {"host": "192.0.2.10"}, notify_buttons.RELEASE)
    assert out.status == "accepted"
    assert calls == [("Release", {"host": "192.0.2.10"})]
    assert _received(store, req.id) == ["accepted: released"]


def test_release_of_a_force_already_gone_is_a_no_op(store, sent, monkeypatch):
    calls = []
    monkeypatch.setattr(notify_buttons, "_store", lambda: store)
    monkeypatch.setattr(bc, "status", lambda host: {"available": True, "vpp_active": False})
    monkeypatch.setattr(bc, "execute", lambda cmd, **kw: calls.append(cmd) or {"ok": True})
    req, out = _ask_then_restart(store, notify_buttons.FORCE_RUNNING, RELEASE_BUTTONS, 900,
                                 {"host": "192.0.2.10"}, notify_buttons.RELEASE)
    assert out.status == "accepted" and calls == []
    assert _received(store, req.id) == ["accepted: already released"]


def test_acknowledge_tapped_after_a_restart_acknowledges(store, sent, monkeypatch):
    monkeypatch.setattr(notify_buttons, "_store", lambda: store)
    alerts.reset()
    aid = alerts.raise_event(store, "gw1", "COMMAND_REFUSED", "Force rejected", now=1.0)
    req, out = _ask_then_restart(store, notify_buttons.ALERT,
                                 [Button(notify_buttons.ACK, "Acknowledge")], 3600,
                                 {"alert_id": aid, "gateway_id": "gw1"}, notify_buttons.ACK)
    assert out.status == "accepted"
    assert store.alert(aid)["acked_by"] == "source:ha"
    assert _received(store, req.id) == ["accepted: acknowledged"]
    alerts.reset()


def test_acknowledging_an_alert_already_acknowledged_is_a_no_op(store, sent, monkeypatch):
    monkeypatch.setattr(notify_buttons, "_store", lambda: store)
    alerts.reset()
    aid = alerts.raise_event(store, "gw1", "COMMAND_REFUSED", "Force rejected", now=1.0)
    alerts.ack(store, aid, "ui", now=2.0)
    req, out = _ask_then_restart(store, notify_buttons.ALERT,
                                 [Button(notify_buttons.ACK, "Acknowledge")], 3600,
                                 {"alert_id": aid, "gateway_id": "gw1"}, notify_buttons.ACK)
    assert out.status == "accepted"
    assert store.alert(aid)["acked_by"] == "source:ui"
    assert _received(store, req.id) == ["accepted: already acknowledged"]
    alerts.reset()


# ── a schedule holding for its Ask ────────────────────────────────────────────
@pytest.fixture
def loop():
    lp = asyncio.new_event_loop()
    t = threading.Thread(target=lp.run_forever, daemon=True)
    t.start()
    yield lp
    lp.call_soon_threadsafe(lp.stop)
    t.join(2)


@pytest.fixture
def bridge(store, sent, loop, monkeypatch):
    """The scheduler with a real Notifier on its own loop; ``restart()`` rebuilds it on
    the same database and forgets everything the scheduler held in memory."""
    monkeypatch.setattr(sch, "ha_snapshot", lambda st: {})
    monkeypatch.setattr(actionable, "_loop", loop)

    def start():
        _clear()
        monkeypatch.setattr(actionable, "_notifier", actionable.build(store, SETTINGS))
        return actionable._notifier

    def tap(verb, rid):
        return asyncio.run_coroutine_threadsafe(
            actionable._notifier.on_tap(Tap("home", verb, rid, None, {})), loop).result(5)
    start()
    yield types.SimpleNamespace(restart=start, tap=tap)
    _clear()


def _clear():
    for d in (sch._asks, sch._window_inside, sch._window_key, sch._gated_day, sch._dwell_since):
        d.clear()


def _schedule(st, sid="s1", ask=ASK, **spec):
    st.create_schedule(sid=sid, name=f"Rule {sid}", spec={
        "gateway_id": "gw", "fire_at": "18:00", "duration_min": 60, "conditions": [],
        "action": {}, "ha_actions": [], "ask": ask, **spec})


def _tick(st, now=NOW):
    return sch.tick(settings=None, client=None, store=st, state={}, gateway_id="gw", now=now)


def _settle(sid="s1"):
    sch._asks[f"gw:{sid}"]["fut"].result(timeout=5)


def _occ(st, sid="s1"):
    return st.occurrences_for(sid)[0]


def _asked(st, sid="s1"):
    """The request id the run recorded, once the question has gone out."""
    for _ in range(200):
        rid = _occ(st, sid).get("ask_request_id")
        if rid:
            return rid
        time.sleep(0.01)
    raise AssertionError("the run never recorded its question")


def _log(st, sid="s1"):
    return [(r["status"], r["result"]) for r in st.schedule_log(schedule_id=sid)][::-1]


@pytest.mark.parametrize("tap_before_tick", [False, True])
def test_a_holding_run_finds_its_question_again_after_a_restart(store, sent, bridge,
                                                               tap_before_tick):
    _schedule(store)
    assert _tick(store) == []
    rid = _asked(store)
    bridge.restart()
    if tap_before_tick:                    # answered before the scheduler looked again
        assert bridge.tap(YES, rid).status == "accepted"
    assert _tick(store, NOW + dt.timedelta(seconds=15)) == []
    assert len(sent) == 1, "not asked again"
    if not tap_before_tick:
        assert bridge.tap(YES, rid).status == "accepted"
    _settle()
    assert [f["id"] for f in _tick(store, NOW + dt.timedelta(seconds=30))] == ["s1"]
    assert _occ(store)["status"] == "ok"
    assert ("continuing", "answered Yes") in _log(store)
    assert _tick(store, NOW + dt.timedelta(seconds=45)) == []
    assert len(sent) == 1


def _expire_while_down(store):
    store._conn.execute("UPDATE notify_requests SET expires_at = expires_at - 400")
    store._conn.commit()


@pytest.mark.parametrize("rule,fires", [("continue", True), ("skip", False)])
def test_a_question_that_expired_while_down_follows_if_no_reply_once(store, sent, bridge,
                                                                     rule, fires):
    _schedule(store, ask={**ASK, "if_no_reply": rule})
    _tick(store)
    _asked(store)
    _expire_while_down(store)
    bridge.restart()
    _tick(store, NOW + dt.timedelta(seconds=15))
    _settle()
    first = _tick(store, NOW + dt.timedelta(seconds=30))
    later = _tick(store, NOW + dt.timedelta(seconds=45)) + _tick(store, NOW + dt.timedelta(seconds=60))
    assert [f["id"] for f in first + later] == (["s1"] if fires else [])
    assert _occ(store)["status"] == ("ok" if fires else "skipped")
    assert sum(f"(if no reply: {rule})" in r for _, r in _log(store)) == 1
    assert len(sent) == 1


def test_a_run_whose_window_ended_while_down_is_neither_asked_nor_run(store, sent, bridge):
    _schedule(store, ask={**ASK, "if_no_reply": "continue"})
    _tick(store)
    rid = _asked(store)
    bridge.restart()
    bridge.tap(YES, rid)
    assert _tick(store, NOW + dt.timedelta(hours=1)) == []
    assert len(sent) == 1


def test_the_answer_is_still_known_to_the_run_after_a_restart(store, sent, bridge):
    _schedule(store, ask={**ASK, "choices": [{"label": "Full", "then": "run"},
                                             {"label": "Not today", "then": "skip"}]})
    _tick(store)
    rid = _asked(store)
    bridge.tap("CHOICE_1", rid)
    _settle()
    assert [f["id"] for f in _tick(store, NOW + dt.timedelta(seconds=15))] == ["s1"]
    bridge.restart()
    assert _tick(store, NOW + dt.timedelta(seconds=30)) == []
    entry = {"id": "s1", "_wkey": _occ(store)["occurrence_key"]}
    assert sch._ask_answer(entry, "gw") == {"ask.answer": "Full"}
    assert len(sent) == 1
