"""Trusted networks (#457 phase 1), the Security switch and roles (phase 3).

A request from an address outside the trusted networks gets 403. An upgraded install
trusts any network, so nothing changes for it; a new install trusts the private ranges
and loopback. Home Assistant ingress and ``/api/live`` (the Supervisor watchdog) are
always allowed. The rest of #457 (HTTPS port, sign-in, roles, tokens) comes later.

Whether this is an upgrade or a new install is decided once, on the first start of this
version: an install that already has an ``install_date`` (set on every first start since
the first public release) is an upgrade. The answer and the list are kept in the store's
``app_config``.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import time

from . import environment

log = logging.getLogger(__name__)

ANY = "any"
#: A new install's trusted networks: the private ranges and loopback, IPv4 and IPv6.
PRIVATE = ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8",
           "fc00::/7", "fe80::/10", "::1/128"]
#: Home Assistant's ingress proxy: every sidebar-panel request comes from here.
INGRESS_IP = "172.30.32.2"
#: Always allowed, whatever the list: the Supervisor watchdog's health check.
ALWAYS_PATHS = ("/api/live",)
#: With Security on, open on the HTTPS port without signing in (plus /static/).
OPEN_PATHS = ("/signin", "/api/auth/login", "/api/auth/me")

_KIND_KEY = "security_install"
_NETS_KEY = "security_trusted_networks"
_ON_KEY = "security_enabled"
_LOG_EVERY_S = 600.0
_last_logged: dict[str, float] = {}


def decide_install(store) -> str:
    """``upgrade`` or ``new``, decided once and kept. Call before ``install_date`` is set
    on this start. Without a store there is nothing to keep, so it behaves as an upgrade."""
    if store is None:
        return "upgrade"
    kind = store.get_config(_KIND_KEY)
    if kind in ("upgrade", "new"):
        return kind
    kind = "upgrade" if store.get_config("install_date") else "new"
    store.set_config(_KIND_KEY, kind)
    store.set_config(_NETS_KEY, json.dumps([ANY] if kind == "upgrade" else PRIVATE))
    store.set_config(_ON_KEY, "0" if kind == "upgrade" else "1")
    log.info("Security: %s install; trusted networks: %s", kind,
             "any" if kind == "upgrade" else ", ".join(PRIVATE))
    return kind


def install_kind(store) -> str:
    return (store.get_config(_KIND_KEY) if store is not None else None) or "upgrade"


def trusted_networks(store) -> list[str]:
    """The saved list; ``["any"]`` when nothing is saved or it can't be read."""
    if store is None:
        return [ANY]
    try:
        nets = json.loads(store.get_config(_NETS_KEY) or "null")
    except ValueError:
        return [ANY]
    return nets if isinstance(nets, list) and nets else [ANY]


def parse_networks(items) -> list[str]:
    """Normalise a list of networks or addresses (``192.168.1.0/24``, ``10.0.0.5``, ``any``).
    Raises ValueError naming the first entry that isn't one."""
    if not isinstance(items, list):
        raise ValueError("networks must be a list")
    out: list[str] = []
    for raw in items:
        s = str(raw).strip()
        if not s:
            continue
        if s.lower() == ANY:
            return [ANY]
        try:
            out.append(str(ipaddress.ip_network(s, strict=False)))
        except ValueError:
            raise ValueError(f"'{s}' is not a network or an address") from None
    if not out:
        raise ValueError("add at least one network, or 'any'")
    return out


def _addr(host):
    try:
        a = ipaddress.ip_address(str(host).split("%")[0])
    except ValueError:
        return None
    return a.ipv4_mapped or a if a.version == 6 else a


def is_trusted(host, nets: list[str]) -> bool:
    """True when ``host`` is in one of ``nets``. A request with no IP address (a Unix
    socket, or the test client) is local, so it is trusted."""
    if ANY in nets:
        return True
    a = _addr(host)
    if a is None:
        return True
    for n in nets:
        try:
            if a in ipaddress.ip_network(n, strict=False):
                return True
        except ValueError:
            continue
    return False


def is_ingress(host, headers) -> bool:
    """A Home Assistant sidebar-panel request: the add-on, the ingress proxy's address,
    and HA's ingress header."""
    return (environment.IS_HA_ADDON and str(host) == INGRESS_IP
            and bool(headers.get("X-Ingress-Path")))


def allowed(host, path: str, headers, nets: list[str]) -> bool:
    if path in ALWAYS_PATHS or is_trusted(host, nets):
        return True
    return is_ingress(host, headers)


def log_refused(host, path: str, now: float | None = None) -> None:
    """One WARNING per address per 10 minutes, so a scan can't flood the log."""
    now = time.time() if now is None else now
    key = str(host)
    if now - _last_logged.get(key, 0.0) < _LOG_EVERY_S:
        return
    _last_logged[key] = now
    log.warning("Refused %s from %s: not in the trusted networks "
                "(Settings → Admin → Security). Further refusals from it are not logged "
                "for 10 minutes.", path, host)


def save(store, nets: list[str], client_host, headers) -> list[str]:
    """Save the list. Refused when it would shut out the browser saving it, unless that
    browser came through Home Assistant ingress, which is always allowed."""
    nets = parse_networks(nets)
    if not is_trusted(client_host, nets) and not is_ingress(client_host, headers):
        raise ValueError(f"your address ({client_host}) is not in this list; "
                         "saving it would shut you out")
    store.set_config(_NETS_KEY, json.dumps(nets))
    log.info("Security: trusted networks set to %s", ", ".join(nets))
    return nets


# ── the Security switch (phase 3) ─────────────────────────────────────────────────
def enabled(store) -> bool:
    """On: sign-in on the HTTPS port, roles, and 8101 redirecting there. Off for an
    upgrade and on for a new install until changed."""
    if store is None:
        return False
    v = store.get_config(_ON_KEY)
    return v == "1" if v in ("0", "1") else install_kind(store) == "new"


def set_enabled(store, on: bool) -> None:
    store.set_config(_ON_KEY, "1" if on else "0")
    log.info("Security switched %s", "on" if on else "off")


# ── roles (phase 3): who may do what ──────────────────────────────────────────────
#: Battery commands: force, release, mode, reserve, off-grid, and acknowledging an alert.
BATTERY = ("/api/battery/command", "/api/dispatch", "/api/mode", "/api/offgrid",
           "/api/cloud/reserve", "/api/cloud/set-mode", "/api/cloud/hold/clear",
           "/api/alerts/")
#: Schedules: add, edit, switch, run, stop, import.
SCHEDULES = ("/api/schedules",)
#: Any signed-in account: their own session and password, and the disclaimer.
SELF = ("/api/auth/", "/api/disclaimer/ack")
#: Reads only an admin may make.
ADMIN_READS = ("/api/security/users", "/api/security/signins")
READ_METHODS = ("GET", "HEAD", "OPTIONS")


def _under(path: str, prefixes) -> bool:
    """``path`` is one of ``prefixes`` or below one (``/api/mode``, ``/api/alerts/7/ack``)."""
    return any(path == p.rstrip("/") or path.startswith(p.rstrip("/") + "/") for p in prefixes)


def required(method: str, path: str) -> tuple[str, ...]:
    """The roles allowed to make this request. Anything not listed is admin only."""
    if _under(path, SELF):
        return ("admin", "user", "viewer", "api")
    if method.upper() in READ_METHODS:
        if _under(path, ADMIN_READS):
            return ("admin",)
        if not path.startswith("/api/"):
            return ("admin", "user", "viewer")      # pages: api accounts have no web UI
        return ("admin", "user", "viewer", "api")
    if _under(path, BATTERY):
        return ("admin", "user", "api")
    if _under(path, SCHEDULES):
        return ("admin", "user")
    return ("admin",)


def can(role: str, method: str, path: str) -> bool:
    return role in required(method, path)


# ── Home Assistant users (phase 3b) ───────────────────────────────────────────────
#: HA's user groups (homeassistant/auth/const.py), sent by the Supervisor 2026.10.4 and
#: later as ``X-Remote-User-Groups``; owners come with ``system-admin`` folded in.
HA_GROUP_ROLES = (("system-admin", "admin"), ("system-read-only", "viewer"),
                  ("system-users", "user"))


def ingress_principal(headers, security_on: bool) -> dict:
    """Who a sidebar-panel request is, and their role: from HA's group when the Supervisor
    sends it; without it, admin while Security is off (as before) and user while it is on."""
    raw = headers.get("X-Remote-User-Groups")
    groups = [g.strip() for g in raw.split(",") if g.strip()] if raw else []
    role = next((r for g, r in HA_GROUP_ROLES if g in groups), None)
    if role is None:
        role = "user" if (groups or security_on) else "admin"
    return {"username": headers.get("X-Remote-User-Name") or "Home Assistant", "role": role,
            "via": "ingress", "groups_known": bool(groups)}
