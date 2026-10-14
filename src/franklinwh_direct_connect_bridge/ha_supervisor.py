"""Zero-config MQTT from the Home Assistant Supervisor.

HA add-ons with ``hassio_api: true`` and ``services: [mqtt:want]`` can ask the
Supervisor for the Mosquitto add-on's broker host/port AND credentials, so the
user never has to type them. The Supervisor injects ``SUPERVISOR_TOKEN`` and
proxies its API at ``http://supervisor``. We use stdlib ``urllib.request`` (like
``notify.py``) — no new dependency — and NEVER raise: every failure degrades to a
``{"found": False, "error": ...}`` result so startup can't be blocked or crashed.
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.request

from .environment import IS_HA_ADDON

log = logging.getLogger("franklinwh_direct_connect_bridge.ha_supervisor")

# Broker hosts that mean "nothing configured yet" (schema default / add-on default).
_UNSET_HOSTS = {"core-mosquitto", ""}


def discover_mqtt() -> dict:
    """Ask the Supervisor for the registered MQTT service. Never raises.

    Returns a dict with ``found`` and, on success, ``host``/``port``/``username``/
    ``password``/``ssl``/``source``. On any failure returns ``found: False`` with a
    human ``error`` explaining what to fix.
    """
    if not IS_HA_ADDON:
        return {"found": False, "error": "not running as an HA add-on", "source": "dev"}

    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        return {"found": False,
                "error": "SUPERVISOR_TOKEN not set — is hassio_api enabled?"}

    try:
        req = urllib.request.Request(
            "http://supervisor/services/mqtt",
            headers={"Authorization": f"Bearer {token}"},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            payload = json.loads(resp.read().decode())
        data = payload.get("data") or {}
        if not data:
            return {"found": False,
                    "error": "No MQTT service registered — install the Mosquitto add-on"}
        return {
            "found": True,
            "host": data.get("host", ""),
            "port": int(data.get("port", 1883)),
            "username": data.get("username", ""),
            "password": data.get("password", ""),
            "ssl": bool(data.get("ssl", False)),
            "source": "supervisor",
        }
    except Exception as e:  # noqa: BLE001 — discovery must never raise
        log.warning("MQTT discovery via Supervisor failed: %s", e)
        return {"found": False, "error": str(e)}


def host_timezone() -> str | None:
    """The HOST's timezone from the Supervisor, e.g. ``Australia/Sydney``. Never raises.

    An add-on container has no timezone of its own, so without this it runs UTC and every
    log line, chart label and ``datetime.now()`` is hours out from what the owner sees.
    (Schedules are unaffected since #41 — those follow the aGate's clock, not this one.)

    Read in Python rather than through ``bashio::info.timezone``: franklinwh-modbus-bridge
    reports (commit ``137146a``) that bashio returns "Unable to access the API, forbidden"
    on real add-on installs while the identical token works from Python in the same boot,
    and a shell guard cannot tell a refusal from "no timezone set" — so it fails silently
    and the container stays on UTC. Their finding, cited; not independently reproduced here.
    """
    if not IS_HA_ADDON:
        return None
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        return None
    try:
        req = urllib.request.Request(
            "http://supervisor/info",
            headers={"Authorization": f"Bearer {token}"},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            payload = json.loads(resp.read().decode())
        tz = ((payload.get("data") or {}).get("timezone") or "").strip()
        return tz or None
    except Exception as e:  # noqa: BLE001 — a missing timezone must never block startup
        log.warning("host timezone lookup via Supervisor failed: %s", e)
        return None


def apply_host_timezone() -> str | None:
    """Set the process timezone from the Supervisor. Returns what was applied, or None.

    ``time.tzset()`` is what makes it take effect for anything already imported; setting
    ``TZ`` alone changes nothing in a running process.
    """
    tz = host_timezone()
    if not tz:
        return None
    try:
        os.environ["TZ"] = tz
        time.tzset()
    except Exception as e:  # noqa: BLE001
        log.warning("could not apply host timezone %r: %s", tz, e)
        return None
    log.info("timezone set from the Supervisor: %s", tz)
    return tz


def apply_supervisor_mqtt(settings) -> bool:
    """Fill in unset MQTT creds from the Supervisor, in place, when it makes sense.

    Only acts when running as an add-on with MQTT enabled and the creds still look
    like defaults (no host, or the ``core-mosquitto`` placeholder, AND no username).
    On success mutates ``settings`` and returns True; otherwise returns False. Never
    raises — a discovery failure just leaves the user-supplied creds untouched.
    """
    if not (IS_HA_ADDON and getattr(settings, "mqtt_enabled", False)):
        return False
    host = (getattr(settings, "mqtt_host", "") or "").strip()
    username = (getattr(settings, "mqtt_username", "") or "").strip()
    if not (host in _UNSET_HOSTS and not username):
        return False  # user supplied explicit creds — respect them

    result = discover_mqtt()
    if not result.get("found"):
        log.info("MQTT auto-config skipped: %s", result.get("error"))
        return False
    try:
        settings.mqtt_host = result["host"]
        settings.mqtt_port = result["port"]
        settings.mqtt_username = result.get("username", "")
        settings.mqtt_password = result.get("password", "")
    except Exception as e:  # noqa: BLE001 — never block startup
        log.warning("MQTT auto-config could not apply creds: %s", e)
        return False
    log.info("MQTT auto-configured from Supervisor: %s:%s",
             result["host"], result["port"])
    return True
