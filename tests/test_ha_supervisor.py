"""ha_supervisor: discover_mqtt / apply_supervisor_mqtt degrade gracefully (A2).

These never touch the network in the test env (not an add-on), so they exercise the
graceful-failure paths without a live Supervisor.
"""

from franklinwh_local_bridge import environment as env
from franklinwh_local_bridge import ha_supervisor as hs
from franklinwh_local_bridge.config import Settings


def test_discover_not_addon(monkeypatch):
    monkeypatch.setattr(hs, "IS_HA_ADDON", False)
    r = hs.discover_mqtt()
    assert r["found"] is False
    assert r["source"] == "dev"


def test_discover_addon_no_token(monkeypatch):
    monkeypatch.setattr(hs, "IS_HA_ADDON", True)
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    r = hs.discover_mqtt()
    assert r["found"] is False
    assert "SUPERVISOR_TOKEN" in r["error"]


def test_discover_never_raises_on_network_error(monkeypatch):
    monkeypatch.setattr(hs, "IS_HA_ADDON", True)
    monkeypatch.setenv("SUPERVISOR_TOKEN", "x")

    def boom(*a, **k):
        raise OSError("no route to supervisor")

    monkeypatch.setattr(hs.urllib.request, "urlopen", boom)
    r = hs.discover_mqtt()
    assert r["found"] is False
    assert "no route" in r["error"]


def test_apply_noop_when_not_addon(monkeypatch):
    monkeypatch.setattr(hs, "IS_HA_ADDON", False)
    s = Settings(mqtt_enabled=True)
    assert hs.apply_supervisor_mqtt(s) is False


def test_apply_respects_user_creds(monkeypatch):
    # User set an explicit host → we must NOT overwrite it, even in add-on mode.
    monkeypatch.setattr(hs, "IS_HA_ADDON", True)
    s = Settings(mqtt_enabled=True, mqtt_host="my-broker.local", mqtt_username="me")
    assert hs.apply_supervisor_mqtt(s) is False
    assert s.mqtt_host == "my-broker.local"


def test_apply_fills_defaults_from_supervisor(monkeypatch):
    monkeypatch.setattr(hs, "IS_HA_ADDON", True)
    monkeypatch.setattr(hs, "discover_mqtt", lambda: {
        "found": True, "host": "core-mosquitto-real", "port": 1884,
        "username": "svc", "password": "pw", "ssl": False, "source": "supervisor"})
    s = Settings(mqtt_enabled=True)  # default host core-mosquitto, no username
    assert hs.apply_supervisor_mqtt(s) is True
    assert s.mqtt_host == "core-mosquitto-real"
    assert s.mqtt_port == 1884
    assert s.mqtt_username == "svc"
    assert s.mqtt_password == "pw"
