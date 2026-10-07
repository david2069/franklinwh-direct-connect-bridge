"""HA notification transition logic + no-op safety (no HA API)."""

from franklinwh_direct_connect_bridge.config import Settings
from franklinwh_direct_connect_bridge.notify import Notifier, transitions


def test_transitions_only_on_change():
    assert transitions(None, {"ok": True, "modbus_502": True}) == []      # first read: no notify
    assert transitions({"ok": True, "modbus_502": True},
                       {"ok": True, "modbus_502": True}) == []            # unchanged: no notify

    t = transitions({"ok": True, "modbus_502": True},
                    {"ok": False, "modbus_502": True})
    assert len(t) == 1 and "UNREACHABLE" in t[0][1]

    t = transitions({"ok": False, "modbus_502": False},
                    {"ok": True, "modbus_502": True})
    assert len(t) == 2                                                     # both recovered


def test_notifier_is_noop_without_ha_api(caplog, monkeypatch):
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    n = Notifier(Settings(ha_notify=True))          # no supervisor token, no ha_url/token
    n.notify("t", "m")                              # must not raise
    assert n.base == "" and n.token == ""


# -- regression: target attributes must exist before notify() is called --------
def test_target_attributes_readable_before_notify():
    """POST /api/notify/test inspects .enabled/.token/.base on a fresh Notifier.

    They used to be created only inside notify(), so that check raised
    AttributeError and the endpoint 500'd (seen in production logs 2026-08-23:
    "'Notifier' object has no attribute 'enabled'").
    """
    from franklinwh_direct_connect_bridge.config import Settings
    from franklinwh_direct_connect_bridge.notify import Notifier

    n = Notifier(Settings())
    assert isinstance(n.enabled, bool)     # no AttributeError
    assert isinstance(n.token, str)
    assert isinstance(n.base, str)


def test_notify_test_endpoint_does_not_500_without_a_target(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from franklinwh_direct_connect_bridge import app as app_module
    from franklinwh_direct_connect_bridge import config, environment

    monkeypatch.setattr(environment, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "_settings", None)
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    c = TestClient(app_module.create_app())
    r = c.post("/api/notify/test")
    assert r.status_code == 200, r.text        # was 500
    assert r.json()["ok"] is False             # and says why
    config._settings = None


def test_target_reflects_live_settings_edits():
    """The properties must stay live — that was the reason for the original design."""
    from franklinwh_direct_connect_bridge.config import Settings
    from franklinwh_direct_connect_bridge.notify import Notifier

    s = Settings()
    s.ha_url, s.ha_token, s.ha_notify = "", "", True
    n = Notifier(s)
    assert n.base == "" and n.token == ""
    s.ha_url, s.ha_token = "http://ha.local:8123", "tok"
    assert n.base == "http://ha.local:8123/api"
    assert n.token == "tok"
