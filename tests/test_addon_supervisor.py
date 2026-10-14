"""FEAT-HA-ADDON-PARITY — the two gaps found by reviewing franklinwh-modbus-bridge's commits.

1. MQTT auto-config ran ONCE at startup, so an add-on installed before Mosquitto kept
   retrying the same unset broker for ever and never noticed when Mosquitto appeared.
2. Nothing set a timezone, so an add-on container runs UTC and every log line and rendered
   local time is hours out from what the owner sees.
"""
import json
import os

import pytest

from franklinwh_direct_connect_bridge import ha_supervisor as hs


class _Resp:
    def __init__(self, payload):
        self._b = json.dumps(payload).encode()

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def _as_addon(monkeypatch):
    monkeypatch.setattr(hs, "IS_HA_ADDON", True)
    monkeypatch.setenv("SUPERVISOR_TOKEN", "t0ken")


# ── host timezone ────────────────────────────────────────────────────────────
def test_host_timezone_read_from_the_supervisor(_as_addon, monkeypatch):
    seen = {}

    def _urlopen(req, timeout=0):
        seen["url"] = req.full_url
        return _Resp({"data": {"timezone": "Australia/Sydney"}})

    monkeypatch.setattr(hs.urllib.request, "urlopen", _urlopen)
    assert hs.host_timezone() == "Australia/Sydney"
    assert seen["url"] == "http://supervisor/info"


def test_host_timezone_is_none_off_addon(monkeypatch):
    monkeypatch.setattr(hs, "IS_HA_ADDON", False)
    assert hs.host_timezone() is None


def test_host_timezone_survives_a_refusal(_as_addon, monkeypatch):
    """The failure mode that made bashio unusable: the API refuses, and it must not raise."""
    def _urlopen(req, timeout=0):
        raise OSError("Unable to access the API, forbidden")

    monkeypatch.setattr(hs.urllib.request, "urlopen", _urlopen)
    assert hs.host_timezone() is None
    assert hs.apply_host_timezone() is None


def test_apply_host_timezone_actually_changes_the_process_clock(_as_addon, monkeypatch):
    """Setting TZ alone does nothing to a running process — tzset() is the operative call."""
    import time as _time
    before = os.environ.get("TZ")
    monkeypatch.setattr(hs.urllib.request, "urlopen",
                        lambda req, timeout=0: _Resp({"data": {"timezone": "Asia/Kolkata"}}))
    try:
        assert hs.apply_host_timezone() == "Asia/Kolkata"
        assert os.environ["TZ"] == "Asia/Kolkata"
        # Kolkata is UTC+5:30 — a half-hour zone no host in this project sits in, so a
        # stale clock cannot pass this by coincidence.
        assert _time.timezone // 60 == -330 or _time.altzone // 60 == -330
    finally:
        if before is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = before
        _time.tzset()


# ── re-asking for a broker that appears later ────────────────────────────────
def test_mqtt_autoconfig_applies_when_mosquitto_appears_later(_as_addon, monkeypatch):
    """First call finds nothing; the second must still apply, not be skipped as 'done'."""
    class S:
        mqtt_enabled = True
        mqtt_host = "core-mosquitto"      # the add-on schema default = "unset"
        mqtt_username = ""
        mqtt_password = ""
        mqtt_port = 1883

    s = S()
    calls = {"n": 0}

    def _urlopen(req, timeout=0):
        calls["n"] += 1
        if calls["n"] == 1:
            return _Resp({"data": {}})           # Mosquitto not installed yet
        return _Resp({"data": {"host": "core-mosquitto-real", "port": 1884,
                               "username": "addons", "password": "pw"}})

    monkeypatch.setattr(hs.urllib.request, "urlopen", _urlopen)

    assert hs.apply_supervisor_mqtt(s) is False
    assert s.mqtt_host == "core-mosquitto", "nothing to apply yet"

    assert hs.apply_supervisor_mqtt(s) is True
    assert (s.mqtt_host, s.mqtt_port, s.mqtt_username) == ("core-mosquitto-real", 1884, "addons")


def test_user_supplied_broker_is_never_overwritten(_as_addon, monkeypatch):
    class S:
        mqtt_enabled = True
        mqtt_host = "192.0.2.50"
        mqtt_username = "me"
        mqtt_password = "secret"
        mqtt_port = 1883

    s = S()
    monkeypatch.setattr(hs.urllib.request, "urlopen",
                        lambda req, timeout=0: _Resp({"data": {"host": "core-mosquitto",
                                                               "port": 1883}}))
    assert hs.apply_supervisor_mqtt(s) is False
    assert s.mqtt_host == "192.0.2.50" and s.mqtt_username == "me"


def test_poller_rechecks_the_supervisor_inside_its_retry():
    """The loop existed; it retried with the SAME unset broker for ever."""
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1]
           / "src/franklinwh_direct_connect_bridge/poller.py").read_text()
    heal = src.split("Self-heal:", 1)[1].split("Honor UI-requested", 1)[0]
    assert "apply_supervisor_mqtt" in heal, (
        "the retry no longer re-asks the Supervisor; a broker installed after this add-on "
        "will never be discovered"
    )
    assert heal.index("apply_supervisor_mqtt") < heal.index("_start_mqtt"), \
        "re-config must happen before the connection attempt it is meant to fix"
