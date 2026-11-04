"""#464: the Notifications check (GET /api/notify/checks), the Test critical alert, the
kept Test with buttons result, and the check in Support info (redacted)."""
import asyncio
import json
import types
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from franklinwh_ha_notify.listener import Tap

from franklinwh_direct_connect_bridge import (actionable, app as app_module, config, db,
                                              ha_instances, notify)

from test_notify_buttons import sent, store  # noqa: F401

PKG = Path(app_module.__file__).parent


@pytest.fixture
def probe(monkeypatch):
    """Home Assistant's /api/ answer to the instance probe; ``probe.result`` to change it."""
    calls = []

    def fake(base_url, token):
        calls.append((base_url, token))
        return fake.result
    fake.result, fake.calls = {"ok": True, "message": "API running."}, calls
    monkeypatch.setattr(ha_instances, "probe", fake)
    return fake


@pytest.fixture
def ha_posts(monkeypatch):
    class Posts(list):
        pass
    out = Posts()

    def fake_urlopen(req, timeout=None):
        out.append((req.full_url, json.loads(req.data)))
        if fake_urlopen.fail:
            raise OSError(fake_urlopen.fail)
        return types.SimpleNamespace(status=200)
    fake_urlopen.fail = ""
    monkeypatch.setattr(notify.urllib.request, "urlopen", fake_urlopen)
    out.ctl = fake_urlopen
    return out


@pytest.fixture
def c(store, sent, probe, monkeypatch):  # noqa: F811
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    monkeypatch.setattr(db, "get_store", lambda s: store)
    s = config.get_settings()
    s.ha_notify, s.ha_url, s.ha_token = True, "", ""
    n = actionable.build(store, types.SimpleNamespace(ha_notify=True))
    monkeypatch.setattr(actionable, "_notifier", n)
    client = TestClient(app_module.create_app())
    client.n = n
    return client


def _by_id(body):
    return {x["id"]: x for x in body["checks"]}


# ── the checks ─────────────────────────────────────────────────────────────────
def test_all_set_up_and_working(c, probe):
    c.n._listeners = {"home": (types.SimpleNamespace(
        connected=types.SimpleNamespace(is_set=lambda: True), last_error=None), None)}
    body = c.get("/api/notify/checks").json()
    ch = _by_id(body)
    assert [x["id"] for x in body["checks"]] == ["push_switch", "ha_instance", "listener:home",
                                                  "phones", "last_test", "route"]
    assert ch["push_switch"]["status"] == "pass"
    assert ch["ha_instance"]["status"] == "pass" and '"Home"' in ch["ha_instance"]["detail"]
    assert probe.calls == [("http://ha.test:8123", "t1")]        # the default instance
    assert ch["listener:home"]["status"] == "pass"
    assert ch["phones"]["status"] == "pass" and "1 enabled phone" in ch["phones"]["detail"]
    assert ch["last_test"]["status"] == "unset" and ch["last_test"]["fix"]
    assert ch["route"]["status"] == "pass" and ch["route"]["source"] == "instance"
    assert all(x["fix"] == "" for x in body["checks"] if x["status"] == "pass")
    assert "t1" not in json.dumps(body)                          # never a token


def test_failures_say_what_to_fix(c, probe):
    probe.result = {"ok": False, "error": "token rejected"}
    c.n._listeners = {"home": (types.SimpleNamespace(
        connected=types.SimpleNamespace(is_set=lambda: False), last_error="auth_invalid"), None)}
    config.get_settings().ha_notify = False
    ch = _by_id(c.get("/api/notify/checks").json())
    assert ch["push_switch"]["status"] == "fail" and "Push notifications" in ch["push_switch"]["fix"]
    assert ch["ha_instance"]["status"] == "fail" and "token" in ch["ha_instance"]["fix"]
    assert (ch["listener:home"]["status"], ch["listener:home"]["detail"]) == ("fail", "auth_invalid")
    assert ch["route"]["status"] == "fail" and "Only the bridge UI" in ch["route"]["detail"]


def test_nothing_set_up(c, store, probe):
    for r in store.ha_instances():
        store.delete_ha_instance(r["id"])
    ch = _by_id(c.get("/api/notify/checks").json())
    assert ch["ha_instance"]["status"] == "unset" and "HA Instances" in ch["ha_instance"]["fix"]
    assert ch["listener"]["status"] == "unset"
    assert ch["phones"]["status"] == "unset"
    assert ch["route"]["status"] == "unset" and ch["route"]["detail"] == "Only the bridge UI"
    assert probe.calls == []


def test_environment_only_is_named_and_probed(c, store, probe):
    for r in store.ha_instances():
        store.delete_ha_instance(r["id"])
    s = config.get_settings()
    s.ha_url, s.ha_token = "http://env.test:8123", "t-env"
    ch = _by_id(c.get("/api/notify/checks").json())
    assert ch["ha_instance"]["status"] == "pass" and "environment" in ch["ha_instance"]["detail"]
    assert probe.calls == [("http://env.test:8123", "t-env")]


def test_a_device_that_is_not_a_phone_fails_the_phone_line(c, store):
    store.update_notify_device("p1", enabled=False)
    store.create_notify_device(dev_id="e1", alias="Mail", instance_id="home",
                               service="notify.email", enabled=True)
    ch = _by_id(c.get("/api/notify/checks").json())
    assert ch["phones"]["status"] == "fail" and "none a mobile_app_* phone" in ch["phones"]["detail"]


# ── the last Test with buttons is kept ─────────────────────────────────────────
def test_test_with_buttons_result_is_kept(c, store):
    r = c.post("/api/ha/notify-devices/test-buttons", json={"device_id": "p1"}).json()
    last = _by_id(c.get("/api/notify/checks").json())["last_test"]
    assert last["status"] == "unset" and last["detail"] == "sent, waiting for a tap" and last["ts"]
    asyncio.run(c.n.on_tap(Tap("home", "YES", r["request_id"], None, {})))
    last = _by_id(c.get("/api/notify/checks").json())["last_test"]
    assert (last["status"], last["detail"]) == ("pass", "tapped Yes")


def test_no_reply_is_kept(c, store, monkeypatch):
    r = c.post("/api/ha/notify-devices/test-buttons", json={"device_id": "p1"}).json()
    req = c.n.requests.get(r["request_id"])
    monkeypatch.setattr(req, "expires_at", 0.0)
    assert c.get(f"/api/ha/notify-devices/test-buttons/{r['request_id']}").json()["expired"]
    last = _by_id(c.get("/api/notify/checks").json())["last_test"]
    assert (last["status"], last["detail"]) == ("fail", "no reply")


# ── Test critical alert ────────────────────────────────────────────────────────
def test_test_alert_runs_the_full_path_without_an_alert_record(c, store, sent, ha_posts):  # noqa: F811
    d = c.post("/api/notify/test-alert").json()
    steps = {s["id"]: s for s in d["steps"]}
    assert steps["ha"]["status"] == "pass" and "Home" in steps["ha"]["detail"]
    assert ha_posts[0][0] == "http://ha.test:8123/api/services/persistent_notification/create"
    assert ha_posts[0][1]["notification_id"] == "fwh_dc_alert_test"
    assert steps["devices"]["status"] == "pass" and steps["devices"]["detail"] == "to 1 of 1 device(s)"
    assert sent[-1]["verbs"] == ["ACK"] and sent[-1]["targets"] == ["mobile_app_phone"]
    assert steps["ack"]["status"] == "waiting" and d["request_id"]
    assert store.alerts() == [] and store.alert_deliveries() == []    # no alert, no modal
    rid = d["request_id"]
    assert c.get(f"/api/notify/test-alert/{rid}").json() == {"answer": None, "expired": False}
    asyncio.run(c.n.on_tap(Tap("home", "ACK", rid, None, {})))
    assert c.get(f"/api/notify/test-alert/{rid}").json()["answer"] == "ACK"
    # Acknowledge dismisses the test's Home Assistant notification, as a real one does.
    assert ha_posts[-1] == ("http://ha.test:8123/api/services/persistent_notification/dismiss",
                            {"notification_id": "fwh_dc_alert_test"})
    assert store.alerts() == []


def test_test_alert_still_reaches_devices_when_home_assistant_fails(c, sent, ha_posts):  # noqa: F811
    ha_posts.ctl.fail = "connection refused"
    steps = {s["id"]: s for s in c.post("/api/notify/test-alert").json()["steps"]}
    assert steps["ha"]["status"] == "fail" and "connection refused" in steps["ha"]["detail"]
    assert steps["devices"]["status"] == "pass" and sent[-1]["verbs"] == ["ACK"]


def test_test_alert_with_no_phone_says_so(c, store, sent):  # noqa: F811
    store.update_notify_device("p1", enabled=False)
    for r in store.ha_instances():
        store.delete_ha_instance(r["id"])
    d = c.post("/api/notify/test-alert").json()
    steps = {s["id"]: s for s in d["steps"]}
    assert steps["ha"]["status"] == "unset" and steps["devices"]["status"] == "unset"
    assert steps["ack"]["status"] == "skipped" and d["request_id"] is None and sent == []


def test_test_alert_answer_is_only_for_test_alerts(c):
    r = c.post("/api/ha/notify-devices/test-buttons", json={"device_id": "p1"}).json()
    assert c.get(f"/api/notify/test-alert/{r['request_id']}").status_code == 404


# ── Support info ───────────────────────────────────────────────────────────────
def test_support_info_has_the_check_redacted(c, store, probe):
    store.update_ha_instance("home", base_url="http://192.0.2.44:8123")
    c.n._listeners = {"home": (types.SimpleNamespace(
        connected=types.SimpleNamespace(is_set=lambda: False),
        last_error="Cannot connect to host ha.home.lan:8123 ws://192.0.2.44:8123/api/websocket"),
        None)}
    body = c.get("/api/support-info").json()
    rows = {r["check"]: r for r in body["notifications"]}
    assert set(rows) == {"push_switch", "ha_instance", "listener", "phones", "last_test", "route"}
    assert rows["ha_instance"] == {"check": "ha_instance", "status": "pass", "source": "instance"}
    assert rows["listener"]["status"] == "fail"
    text = json.dumps(body["notifications"])
    for secret in ("192.0.2.44", "ws://", "http", "t1", "Home", "Phone", "home.lan"):
        assert secret not in text, secret


# ── the UI ─────────────────────────────────────────────────────────────────────
def test_settings_has_the_check_panel_and_the_test_dialog_without_toasts():
    html = (PKG / "templates/tabs/settings.html").read_text()
    js = (PKG / "static/js/settings_tab.js").read_text()
    assert 'data-testid="notify-checks"' in html and "loadChecks()" in html
    assert 'data-testid="test-alert-dialog"' in html and "runTestAlert()" in html
    body = js[js.index("async loadChecks()"):js.index("async loadNotify()")]
    assert "api/notify/checks" in body and "api/notify/test-alert" in body
    assert "toast" not in body                                  # results stay in the dialog
    assert "notifications check:" in js                         # in the Support info text
