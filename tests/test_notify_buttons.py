"""#374 P3: Release, Acknowledge, Re-discover and the test round trip, through the shared
Notifier. Home Assistant is faked at the package's send(); taps are fed to on_tap."""

import asyncio
import inspect
import threading
import types

import pytest
from fastapi.testclient import TestClient
from franklinwh_ha_notify import notifier as pkg_notifier
from franklinwh_ha_notify.listener import Tap
from franklinwh_ha_notify.send import Delivery, SendResult

from franklinwh_direct_connect_bridge import (actionable, alerts, app as app_module,
                                              battery_control as bc, config, db, environment,
                                              notify_buttons, state, vpp_monitor)
from franklinwh_direct_connect_bridge.state import GatewayState


@pytest.fixture
def store(tmp_path):
    st = db.MetricsStore(str(tmp_path / "bridge.db"))
    st.create_ha_instance(ha_id="home", name="Home", base_url="http://ha.test:8123",
                          token="t1", is_default=True)
    st.create_ha_instance(ha_id="off", name="Off", base_url="http://off.test:8123",
                          token="t2", enabled=False)
    st.create_notify_device(dev_id="p1", alias="Phone", instance_id="home",
                            service="notify.mobile_app_phone", enabled=True)
    st.create_notify_device(dev_id="p2", alias="Muted", instance_id="home",
                            service="mobile_app_muted", enabled=False)
    st.create_notify_device(dev_id="p3", alias="Elsewhere", instance_id="off",
                            service="mobile_app_other", enabled=True)
    yield st
    st.close()


@pytest.fixture
def sent(monkeypatch):
    """Every send the Notifier makes: (title, message, verbs, request id, targets)."""
    out = []

    async def fake_send(instances, targets, title, message, buttons=None, request_id=None):
        out.append({"title": title, "message": message, "request_id": request_id,
                    "verbs": [b.verb for b in buttons or []],
                    "targets": [t.service for t in targets]})
        return SendResult([Delivery(t.key, True) for t in targets])
    monkeypatch.setattr(pkg_notifier, "send", fake_send)
    return out


@pytest.fixture
def running(store, sent, monkeypatch):
    """actionable started on a loop in its own thread, as in the app; no listeners."""
    monkeypatch.setattr(pkg_notifier.Notifier, "listen", lambda self, ids=None: None)
    monkeypatch.setattr(notify_buttons, "_store", lambda: store)
    loop = asyncio.new_event_loop()
    t = threading.Thread(target=loop.run_forever, daemon=True)
    t.start()
    n = asyncio.run_coroutine_threadsafe(
        actionable.start(store, types.SimpleNamespace(ha_notify=True)), loop).result(5)

    def tap(verb, request_id):
        return asyncio.run_coroutine_threadsafe(
            n.on_tap(Tap("home", verb, request_id, None, {})), loop).result(10)
    yield types.SimpleNamespace(n=n, tap=tap, loop=loop)
    asyncio.run_coroutine_threadsafe(actionable.stop(), loop).result(5)
    loop.call_soon_threadsafe(loop.stop)
    t.join(5)
    actionable._loop = None


def _ledger(store, request_id):
    return [r[0] for r in store._conn.execute(
        "SELECT status FROM notify_ledger WHERE direction='RECEIVED' AND request_id=?",
        (request_id,))]


# ── actionable helpers ─────────────────────────────────────────────────────────
def test_targets_are_the_enabled_devices_on_enabled_instances(store):
    assert [(t.instance_id, t.service, t.label) for t in actionable.targets(store)] == \
        [("home", "mobile_app_phone", "Phone")]


def test_submit_runs_on_the_notifier_loop_and_is_none_when_not_running(running):
    async def where():
        return asyncio.get_running_loop()
    assert actionable.submit(where()).result(5) is running.loop


def test_submit_without_a_notifier_closes_the_coroutine():
    async def never():
        raise AssertionError("must not run")
    c = never()
    assert actionable.submit(c) is None
    assert inspect.getcoroutinestate(c) == inspect.CORO_CLOSED


# ── Release / Keep ─────────────────────────────────────────────────────────────
def test_release_tap_runs_the_bridges_release_on_that_host(running, sent, store, monkeypatch):
    calls = []
    monkeypatch.setattr(bc, "execute", lambda cmd, **kw: calls.append((cmd, kw)) or
                        {"ok": True, "result": "released"})
    assert notify_buttons.ask_release(store, "192.0.2.10", "Force running", "Release it?")
    assert sent[-1]["verbs"] == ["RELEASE", "NO"] and sent[-1]["title"] == "Force running"
    assert sent[-1]["targets"] == ["mobile_app_phone"]
    rid = sent[-1]["request_id"]
    assert running.tap("RELEASE", rid).status == "accepted"
    assert calls == [("Release", {"host": "192.0.2.10"})]
    assert _ledger(store, rid) == ["accepted: released"]
    assert running.tap("RELEASE", rid).status == "used"           # single use
    assert len(calls) == 1


def test_keep_tap_leaves_the_force(running, sent, store, monkeypatch):
    calls = []
    monkeypatch.setattr(bc, "execute", lambda cmd, **kw: calls.append(cmd) or {"ok": True})
    notify_buttons.ask_release(store, "192.0.2.10", "t", "m")
    rid = sent[-1]["request_id"]
    running.tap("NO", rid)
    assert calls == [] and _ledger(store, rid) == ["accepted: kept"]


def test_a_refused_release_says_why(running, sent, store, monkeypatch):
    monkeypatch.setattr(bc, "execute", lambda cmd, **kw: {"ok": False, "result": "Modbus client off"})
    notify_buttons.ask_release(store, "192.0.2.10", "t", "m")
    rid = sent[-1]["request_id"]
    running.tap("RELEASE", rid)
    assert _ledger(store, rid) == ["accepted: not released: Modbus client off"]


def test_ask_release_is_false_without_the_notifier(store):
    assert notify_buttons.ask_release(store, "192.0.2.10", "t", "m") is False


def test_vpp_at_boot_asks_release_instead_of_the_plain_push(store, monkeypatch):
    from franklinwh_direct_connect_bridge import notify_engine
    asked, plain = [], []
    monkeypatch.setattr(notify_buttons, "ask_release", lambda *a: asked.append(a) or True)
    monkeypatch.setattr(notify_engine, "fire", lambda *a, **k: plain.append(a) or 1)
    vpp_monitor.reset()
    r = vpp_monitor.check("192.0.2.10", store, boot=True, snapshot={"vpp": True}, label="Home")
    assert r["event"] == "vpp-at-boot"
    assert asked and asked[0][1] == "192.0.2.10" and plain == []


def test_vpp_at_boot_falls_back_to_the_plain_push(store, monkeypatch):
    from franklinwh_direct_connect_bridge import notify_engine
    plain = []
    monkeypatch.setattr(notify_buttons, "ask_release", lambda *a: False)
    monkeypatch.setattr(notify_engine, "fire", lambda *a, **k: plain.append(a) or 1)
    vpp_monitor.reset()
    vpp_monitor.check("192.0.2.10", store, boot=True, snapshot={"vpp": True}, label="Home")
    assert len(plain) == 1


def test_interrupted_force_still_running_asks_release(monkeypatch):
    import time as _t
    asked, plain = [], []

    class St:
        def active_dispatches(self, host=None):
            return [dict(id=1, schedule_id="s1", name="Peak", host="h", watts=-2000,
                         window_end_ts=_t.time() - 60)]

        def end_dispatch(self, *a, **k): pass

        def log_schedule_event(self, *a, **k): pass
    monkeypatch.setattr(bc, "status", lambda host: {"vpp_active": True})
    monkeypatch.setattr(notify_buttons, "ask_release", lambda *a: asked.append(a) or True)
    out = bc.reconcile_interrupted(St(), "h", "notify", notify=lambda a, d, g: plain.append(a))
    assert out[0]["action"] == "notified"
    assert len(asked) == 1 and asked[0][1] == "h" and plain == []
    monkeypatch.setattr(notify_buttons, "ask_release", lambda *a: False)
    bc.reconcile_interrupted(St(), "h", "notify", notify=lambda a, d, g: plain.append(a))
    assert len(plain) == 1                                  # nothing went out: plain push


# ── Acknowledge / Re-discover ──────────────────────────────────────────────────
class _HA:
    def call_service(self, domain, service, data):
        return ""


@pytest.fixture
def gw():
    g = GatewayState(id="gw1", label="Home", configured_host="192.0.2.10")
    state._gateways["gw1"] = g
    yield g
    state._gateways.pop("gw1", None)


def test_unreachable_alert_offers_acknowledge_and_rediscover(running, sent, store, gw):
    alerts.reset()
    alerts.set_condition("gw1", "GATEWAY_UNREACHABLE", True, now=0.0)
    alerts.evaluate(store, now=400.0)
    assert alerts.deliver(store, _HA(), now=401.0) == 1
    assert sent[-1]["verbs"] == ["ACK", "REDISCOVER"]
    rid = sent[-1]["request_id"]
    running.tap("REDISCOVER", rid)
    assert gw.rediscover_requested is True
    assert _ledger(store, rid) == ["accepted: re-discovery requested"]
    alerts.reset()


def test_acknowledge_tap_acknowledges_the_alert_from_ha(running, sent, store, gw):
    alerts.reset()
    aid = alerts.raise_event(store, "gw1", "COMMAND_REFUSED", "Force rejected", now=1.0)
    alerts.deliver(store, _HA(), now=2.0)
    assert sent[-1]["verbs"] == ["ACK"] and sent[-1]["message"] == "Force rejected"
    running.tap("ACK", sent[-1]["request_id"])
    assert store.alert(aid)["acked_by"] == "source:ha"
    alerts.reset()


def test_rediscover_request_sweeps_without_waiting_for_the_streak(monkeypatch):
    from franklinwh_direct_connect_bridge import poller
    sweeps = []
    s = config.get_settings()
    monkeypatch.setattr(s, "mqtt_enabled", False)
    monkeypatch.setattr(s, "poll_interval", 1)
    monkeypatch.setattr(poller.client, "firmware", lambda *a, **k: {"IBG_SN": "SN1"})
    monkeypatch.setattr(poller.client, "summary", lambda *a, **k: {"ok": False, "error": "x"})
    monkeypatch.setattr(poller.client, "still_at_address", lambda host: False)
    monkeypatch.setattr(poller.client, "rediscover", lambda *a, **k: sweeps.append(a[1]))
    g = GatewayState(id="g1", configured_host="192.0.2.10", active_host="192.0.2.10")
    assert g.rediscover_requested is False              # every gateway has the flag, off
    g.rediscover_requested = True

    async def go():
        stop = asyncio.Event()
        t = asyncio.create_task(poller.run_gateway(s, g, stop))
        await asyncio.sleep(1.5)                       # one failed poll: below the streak
        stop.set()
        await asyncio.wait_for(t, timeout=10)
    asyncio.run(go())
    assert sweeps == ["192.0.2.10"] and g.rediscover_requested is False


# ── test round trip ────────────────────────────────────────────────────────────
def test_test_with_buttons_round_trip(store, sent, tmp_path, monkeypatch):
    monkeypatch.setattr(environment, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "_settings", None)
    monkeypatch.setattr(db, "get_store", lambda s: store)
    n = actionable.build(store, types.SimpleNamespace(ha_notify=True))
    monkeypatch.setattr(actionable, "_notifier", n)
    c = TestClient(app_module.create_app())
    r = c.post("/api/ha/notify-devices/test-buttons", json={"device_id": "p1"}).json()
    assert r["ok"] and sent[-1]["verbs"] == ["YES", "NO"]
    rid = r["request_id"]
    assert c.get(f"/api/ha/notify-devices/test-buttons/{rid}").json() == \
        {"answer": None, "expired": False}
    asyncio.run(n.on_tap(Tap("home", "NO", rid, None, {})))
    assert c.get(f"/api/ha/notify-devices/test-buttons/{rid}").json()["answer"] == "NO"
    assert _ledger(store, rid) == ["accepted: No"]


def test_test_with_buttons_refuses_a_target_without_buttons(store, sent, tmp_path, monkeypatch):
    store.create_notify_device(dev_id="e1", alias="Mail", instance_id="home",
                               service="email", enabled=True)
    monkeypatch.setattr(environment, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "_settings", None)
    monkeypatch.setattr(db, "get_store", lambda s: store)
    monkeypatch.setattr(actionable, "_notifier",
                        actionable.build(store, types.SimpleNamespace(ha_notify=True)))
    c = TestClient(app_module.create_app())
    r = c.post("/api/ha/notify-devices/test-buttons", json={"device_id": "e1"}).json()
    assert r["ok"] is False and "cannot show buttons" in r["error"] and sent == []


def test_settings_card_has_the_test_with_buttons_and_shows_the_answer_inline():
    from pathlib import Path
    pkg = Path(app_module.__file__).parent
    html = (pkg / "templates/tabs/settings.html").read_text()
    js = (pkg / "static/js/settings_tab.js").read_text()
    assert 'testButtons(dev)' in html and 'notif.rt[dev.id]' in html
    body = js[js.index("async testButtons(dev)"):js.index("openAddDevice() {")]
    assert "test-buttons" in body and "toast" not in body       # the answer stays on the row


def test_the_notifier_starts_before_the_pollers_and_the_vpp_monitor():
    src = inspect.getsource(app_module.create_app)
    start = src.index("await actionable.start(")
    assert start < src.index("await supervisor.start_poller(")
    assert start < src.index("_th.Thread(target=_vpp_loop")
