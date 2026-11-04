"""#464: persistent notifications go to the default HA instance from Settings, and an
alert reaches the devices even when the persistent notification fails.

Covers the add-on (its own instance, unchanged), Docker with an instance set up, Docker
with only HA_URL/HA_TOKEN, and a failed Home Assistant create that still notifies devices.
"""
import json

import pytest

from franklinwh_direct_connect_bridge import (alerts, app as app_module, config, db,
                                              environment, ha_supervisor, notify)
from franklinwh_direct_connect_bridge.notify import Notifier

from test_notify_buttons import running, sent, store  # noqa: F401


@pytest.fixture(autouse=True)
def _fresh():
    alerts.reset()
    yield
    alerts.reset()


@pytest.fixture
def posts(monkeypatch):
    """Every HTTP POST the core notifier makes: (url, bearer, body)."""
    out = []

    class _Resp:
        status = 200

        def read(self):
            return b"{}"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=None):
        out.append((req.full_url, req.headers.get("Authorization"), json.loads(req.data)))
        return _Resp()
    monkeypatch.setattr(notify.urllib.request, "urlopen", fake_urlopen)
    return out


def _settings(**kw):
    s = config.get_settings()
    s.ha_notify = True
    s.ha_url, s.ha_token = kw.get("ha_url", ""), kw.get("ha_token", "")
    return s


def _store():
    return db.get_store(config.get_settings())


# ── add-on ──────────────────────────────────────────────────────────────────────
def test_addon_goes_to_its_own_instance_unchanged(monkeypatch, posts):
    monkeypatch.setenv("SUPERVISOR_TOKEN", "sup-tok")
    monkeypatch.setattr(ha_supervisor, "IS_HA_ADDON", True)
    s = _settings()
    assert app_module._seed_self_ha_instance(s) is True
    n = Notifier(s)
    t = n.target_info()
    assert (t["source"], t["name"]) == ("instance", "Home Assistant (this add-on)")
    # The same URL and token the add-on always used.
    assert (n.base, n.token) == ("http://supervisor/core/api", "sup-tok")
    n.notify("FranklinWH aGate", "aGate is UNREACHABLE.")
    assert posts == [("http://supervisor/core/api/services/persistent_notification/create",
                      "Bearer sup-tok", {"title": "FranklinWH aGate",
                                         "message": "aGate is UNREACHABLE."})]


def test_addon_without_any_instance_still_uses_the_supervisor(monkeypatch):
    monkeypatch.setenv("SUPERVISOR_TOKEN", "sup-tok")
    n = Notifier(_settings())
    assert n.target_info()["source"] == "supervisor"
    assert (n.base, n.token) == ("http://supervisor/core/api", "sup-tok")


# ── Docker / pip with an instance ───────────────────────────────────────────────
def test_docker_with_an_instance_uses_the_default_instance(monkeypatch, posts):
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    st = _store()
    st.create_ha_instance(ha_id="a", name="Shed", base_url="http://shed.test:8123",
                          token="t-shed")
    st.create_ha_instance(ha_id="b", name="House", base_url="http://house.test:8123/",
                          token="t-house", is_default=True)
    # HA_URL/HA_TOKEN set as well: the instance from Settings wins.
    n = Notifier(_settings(ha_url="http://env.test:8123", ha_token="t-env"))
    t = n.target_info()
    assert (t["source"], t["name"], t["instance_id"]) == ("instance", "House", "b")
    n.notify("FranklinWH firmware updated", "x")
    assert posts[0][:2] == ("http://house.test:8123/api/services/persistent_notification/create",
                            "Bearer t-house")
    assert n.call_service("persistent_notification", "create", {"notification_id": "n"}) == ""
    assert posts[1][0].startswith("http://house.test:8123/api/")


def test_a_disabled_default_falls_to_an_enabled_instance(monkeypatch):
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    st = _store()
    st.create_ha_instance(ha_id="a", name="Off", base_url="http://off.test:8123",
                          token="t1", is_default=True, enabled=False)
    st.create_ha_instance(ha_id="b", name="On", base_url="http://on.test:8123", token="t2")
    assert Notifier(_settings()).target_info()["instance_id"] == "b"


def test_the_alert_monitor_and_poller_notifier_follow_a_live_instance_change(monkeypatch):
    """One long-lived Notifier (alert monitor, poller) sees an instance added later."""
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    n = Notifier(_settings(ha_url="http://env.test:8123", ha_token="t-env"))
    assert n.target_info()["source"] == "environment"
    _store().create_ha_instance(ha_id="h", name="Home", base_url="http://h.test:8123",
                                token="t", is_default=True)
    assert (n.target_info()["source"], n.base) == ("instance", "http://h.test:8123/api")


# ── Docker / pip with only the environment ──────────────────────────────────────
def test_docker_env_only_uses_ha_url_and_token(monkeypatch, posts):
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    n = Notifier(_settings(ha_url="http://env.test:8123/", ha_token="t-env"))
    assert n.target_info()["source"] == "environment"
    n.notify("t", "m")
    assert posts[0][:2] == ("http://env.test:8123/api/services/persistent_notification/create",
                            "Bearer t-env")


def test_all_instances_disabled_falls_back_to_the_environment(monkeypatch):
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    _store().create_ha_instance(ha_id="a", name="Off", base_url="http://off.test:8123",
                                token="t1", is_default=True, enabled=False)
    n = Notifier(_settings(ha_url="http://env.test:8123", ha_token="t-env"))
    assert (n.target_info()["source"], n.base) == ("environment", "http://env.test:8123/api")


def test_nothing_set_up_goes_nowhere(monkeypatch):
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    n = Notifier(_settings())
    assert n.target_info()["source"] == "none"
    assert n.call_service("persistent_notification", "create", {}).startswith("skipped:")


# ── a failed persistent notification still reaches the devices ─────────────────
class FailingHA:
    def __init__(self, *errors):
        self.errors, self.calls = list(errors), []

    def call_service(self, domain, service, data):
        self.calls.append(service)
        return self.errors.pop(0) if self.errors else ""


def test_ha_create_failure_still_notifies_devices(running, sent, store):  # noqa: F811
    a = alerts.raise_event(store, "", "COMMAND_REFUSED", "Force rejected", now=0.0)
    ha = FailingHA("token rejected", "token rejected")
    assert alerts.deliver(store, ha, now=0.0) == 0
    assert [s["verbs"] for s in sent] == [["ACK"]]          # on the phones, with Acknowledge
    assert sent[0]["targets"] == ["mobile_app_phone"]
    # Retries of the HA notification do not send to the phones again.
    alerts.deliver(store, ha, now=15.0)
    alerts.deliver(store, ha, now=45.0)
    assert ha.calls == ["create", "create", "create"]
    assert len(sent) == 1
    assert store.alert_deliveries(a)[0]["delivered_ts"] == 45.0


def test_no_ha_notification_target_still_notifies_devices(running, sent, store):  # noqa: F811
    alerts.raise_event(store, "", "COMMAND_REFUSED", "x", now=0.0)
    alerts.deliver(store, FailingHA("skipped: no Home Assistant API configured"), now=0.0)
    assert len(sent) == 1 and sent[0]["verbs"] == ["ACK"]


def test_a_successful_create_sends_to_the_phones_once(running, sent, store):  # noqa: F811
    a = alerts.raise_event(store, "", "COMMAND_REFUSED", "x", now=0.0)
    assert alerts.deliver(store, FailingHA(), now=0.0) == 1
    assert len(sent) == 1
    alerts.ack(store, a, "ui", now=1.0)
    alerts.deliver(store, FailingHA(), now=2.0)              # the dismiss: no phone send
    assert len(sent) == 1


def test_a_phone_send_error_never_stops_the_outbox(store, monkeypatch):  # noqa: F811
    from franklinwh_direct_connect_bridge import notify_buttons

    def boom(*a, **k):
        raise RuntimeError("no loop")
    monkeypatch.setattr(notify_buttons, "ask_alert", boom)
    a = alerts.raise_event(store, "", "COMMAND_REFUSED", "x", now=0.0)
    assert alerts.deliver(store, FailingHA(), now=0.0) == 1
    assert store.alert_deliveries(a)[0]["delivered_ts"] == 0.0
