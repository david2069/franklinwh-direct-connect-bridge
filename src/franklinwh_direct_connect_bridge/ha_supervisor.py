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
import urllib.error
import urllib.request

from .environment import IS_HA_ADDON

log = logging.getLogger("franklinwh_direct_connect_bridge.ha_supervisor")

#: The Mosquitto broker app's page in Home Assistant (#785), opened in a new tab from the
#: sidebar panel; outside the panel, the My Home Assistant link to it. Home Assistant's own
#: My redirect, not a page path: the path moved when add-ons became apps
#: (``/hassio/addon/…`` is a 404 on 2026.11, measured), and the redirect knows each
#: version's.
MOSQUITTO_URL = "/_my_redirect/supervisor_addon?addon=core_mosquitto"
MOSQUITTO_MY_URL = "https://my.home-assistant.io/redirect/supervisor_addon/?addon=core_mosquitto"
NO_BROKER_ERROR = "No MQTT service registered — install the Mosquitto add-on"
#: "No MQTT broker yet" is logged when it becomes true, not on each check (the wizard
#: checks every 5 s).
_no_broker_logged = False

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

    global _no_broker_logged
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
            return {"found": False, "no_broker": True, "error": NO_BROKER_ERROR}
        _no_broker_logged = False
        return {
            "found": True,
            "host": data.get("host", ""),
            "port": int(data.get("port", 1883)),
            "username": data.get("username", ""),
            "password": data.get("password", ""),
            "ssl": bool(data.get("ssl", False)),
            "source": "supervisor",
        }
    except urllib.error.HTTPError as e:
        # 400 "Service not enabled": no broker app yet. An expected state on a new install,
        # not a failure (#785).
        try:
            body = e.read().decode(errors="replace")
        except Exception:  # noqa: BLE001
            body = ""
        if e.code == 400 and "Service not enabled" in body:
            (log.debug if _no_broker_logged else log.info)(
                "No MQTT broker yet: install the Mosquitto broker app; the Bridge connects "
                "on its own once it is running")
            _no_broker_logged = True
            return {"found": False, "no_broker": True, "error": NO_BROKER_ERROR}
        log.warning("MQTT discovery via Supervisor failed: %s", e)
        return {"found": False, "error": str(e)}
    except Exception as e:  # noqa: BLE001 — discovery must never raise
        log.warning("MQTT discovery via Supervisor failed: %s", e)
        return {"found": False, "error": str(e)}


# ── Home Assistant's discovered MQTT integration (#785, path B) ───────────────────────────
def _ws_frame(data: bytes, opcode: int = 0x1) -> bytes:
    """One client frame: FIN, masked (a client must mask)."""
    import struct
    n = len(data)
    head = bytes([0x80 | opcode])
    if n < 126:
        head += bytes([0x80 | n])
    elif n < 1 << 16:
        head += bytes([0x80 | 126]) + struct.pack("!H", n)
    else:
        head += bytes([0x80 | 127]) + struct.pack("!Q", n)
    mask = os.urandom(4)
    return head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data))


class _WsReader:
    """Reads a server's (unmasked) frames from a socket, answering pings."""

    def __init__(self, sock, buf: bytes = b""):
        self.sock, self.buf = sock, buf

    def _take(self, n: int) -> bytes:
        while len(self.buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError("Home Assistant closed the websocket")
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def message(self) -> dict:
        import struct
        parts: list[bytes] = []
        while True:
            b0, b1 = self._take(2)
            n = b1 & 0x7F
            if n == 126:
                n = struct.unpack("!H", self._take(2))[0]
            elif n == 127:
                n = struct.unpack("!Q", self._take(8))[0]
            mask = self._take(4) if b1 & 0x80 else b""
            data = self._take(n)
            if mask:
                data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
            op = b0 & 0x0F
            if op == 0x8:
                raise ConnectionError("Home Assistant closed the websocket")
            if op == 0x9:
                self.sock.sendall(_ws_frame(data, 0xA))
                continue
            if op == 0xA:
                continue
            parts.append(data)
            if b0 & 0x80:
                return json.loads(b"".join(parts).decode())


def ws_call(payload: dict, *, timeout: float = 5.0) -> object:
    """One command on Home Assistant's websocket API through the Supervisor proxy
    (``ws://supervisor/core/websocket``, authenticated with ``SUPERVISOR_TOKEN``); its
    ``result``. There is no websocket client in the image, so this is the protocol's small
    part this needs. Raises on any failure."""
    import base64
    import socket
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        raise PermissionError("SUPERVISOR_TOKEN not set")
    key = base64.b64encode(os.urandom(16)).decode()
    with socket.create_connection(("supervisor", 80), timeout=timeout) as sock:
        sock.settimeout(timeout)
        sock.sendall((f"GET /core/websocket HTTP/1.1\r\nHost: supervisor\r\n"
                      f"Upgrade: websocket\r\nConnection: Upgrade\r\n"
                      f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = sock.recv(4096)
            if not chunk:
                raise ConnectionError("the Supervisor closed the websocket handshake")
            buf += chunk
        head, buf = buf.split(b"\r\n\r\n", 1)
        status = head.split(b"\r\n", 1)[0].decode(errors="replace")
        if " 101 " not in status + " ":
            raise ConnectionError(f"websocket refused: {status}")
        rd = _WsReader(sock, buf)
        rd.message()                                             # auth_required
        sock.sendall(_ws_frame(json.dumps({"type": "auth", "access_token": token}).encode()))
        auth = rd.message()
        if auth.get("type") != "auth_ok":
            raise PermissionError(f"websocket auth: {auth.get('message') or auth.get('type')}")
        sock.sendall(_ws_frame(json.dumps({"id": 1, **payload}).encode()))
        while True:
            msg = rd.message()
            if msg.get("id") == 1 and msg.get("type") == "result":
                if not msg.get("success"):
                    raise RuntimeError(f"websocket: {(msg.get('error') or {}).get('message')}")
                return msg.get("result")


def mqtt_flow_id() -> str | None:
    """The flow Home Assistant opened when it discovered the Mosquitto broker: handler
    ``mqtt``, source ``hassio``. None when there is none."""
    for f in ws_call({"type": "config_entries/flow/progress"}) or []:
        if f.get("handler") == "mqtt" and (f.get("context") or {}).get("source") == "hassio":
            return f.get("flow_id")
    return None


def confirm_flow(flow_id: str) -> dict:
    """Confirm a discovered flow (its ``hassio_confirm`` step takes no input)."""
    token = os.environ.get("SUPERVISOR_TOKEN") or ""
    req = urllib.request.Request(
        f"http://supervisor/core/api/config/config_entries/flow/{flow_id}",
        data=b"{}", method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode() or "{}")


#: The Supervisor's proxy to Home Assistant's own REST API. An add-on reaches HA here
#: with SUPERVISOR_TOKEN — no long-lived token, nothing for the user to create or paste.
SUPERVISOR_CORE_API = "http://supervisor/core"


def self_instance() -> dict | None:
    """This add-on's OWN Home Assistant, ready to store as an instance. None if not available.

    Running as an add-on, the Home Assistant we publish to is the one we are installed in —
    asking the user to create a long-lived token and paste its URL is asking them for
    something the Supervisor already provides.

    Returns ``{"name", "base_url", "token"}``. The token is the Supervisor's and rotates
    with the add-on, so it is stored like any other and re-read from the environment at
    startup rather than being treated as permanent.
    """
    if not IS_HA_ADDON:
        return None
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        return None
    return {"name": "Home Assistant (this add-on)",
            "base_url": SUPERVISOR_CORE_API,
            "token": token}


def host_lan_subnets() -> list[str]:
    """The HOST's own LAN subnets as ``a.b.c.0/24``, from the Supervisor. Never raises.

    An add-on container sits on the Supervisor's internal Docker network (172.30.32.0/23),
    so anything derived from the container's own interfaces points at that network — and a
    scan of it can never find an aGate. Measured on a live install, 2026-10-15: Discover
    offered ``172.30.33.0/24`` and found nothing, on a site where the aGate was reachable.

    The Supervisor knows the HOST's interfaces, which is where the hardware actually is.
    Docker/HA-internal ranges are filtered out rather than offered.
    """
    if not IS_HA_ADDON:
        return []
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        return []
    try:
        req = urllib.request.Request(
            "http://supervisor/network/info",
            headers={"Authorization": f"Bearer {token}"},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            payload = json.loads(resp.read().decode())
    except Exception as e:  # noqa: BLE001 — never raise; the caller falls back
        log.warning("Supervisor network info failed: %s", e)
        return []

    out: list[str] = []
    for iface in (payload.get("data") or {}).get("interfaces") or []:
        if not iface.get("enabled", True):
            continue
        ipv4 = iface.get("ipv4") or {}
        for addr in ipv4.get("address") or []:
            net = _slash24(str(addr))
            if net and net not in out:
                out.append(net)
    return out


#: Ranges an add-on sees that are NEVER where the aGate lives: the Supervisor's own
#: docker network and the usual docker bridge.
_INTERNAL_PREFIXES = ("172.30.", "172.17.", "172.18.")


def _slash24(cidr: str) -> str | None:
    """``192.0.2.17/24`` -> ``192.0.2.0/24``; None for anything internal or unparsable."""
    ip = cidr.split("/")[0].strip()
    parts = ip.split(".")
    if len(parts) != 4 or not all(p.isdigit() for p in parts):
        return None
    if ip.startswith(_INTERNAL_PREFIXES) or ip.startswith("127."):
        return None
    return f"{parts[0]}.{parts[1]}.{parts[2]}.0/24"


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
    info = supervisor_info()
    tz = ((info or {}).get("timezone") or "").strip()
    return tz or None


def supervisor_info() -> dict | None:
    """The Supervisor's ``/info`` data (timezone, ``hassos``, ``homeassistant``,
    ``operating_system`` …), or None off the add-on or on any failure. Never raises."""
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
        return payload.get("data") or {}
    except Exception as e:  # noqa: BLE001 — must never block startup
        log.warning("Supervisor info lookup failed: %s", e)
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

    Only acts when running as an add-on and the creds still look like defaults (no host,
    or the ``core-mosquitto`` placeholder, AND no username). On success mutates
    ``settings`` and returns True; otherwise returns False. Never raises — a discovery
    failure just leaves the user-supplied creds untouched.

    This runs whether or not publishing is ON. It used to require ``mqtt_enabled``, which
    meant a user turning publishing on found no broker configured and had to go looking
    for one the Supervisor had been able to name all along.
    """
    if not IS_HA_ADDON:
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
