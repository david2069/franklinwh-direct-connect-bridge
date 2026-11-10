"""Authenticated REST client for a sibling FranklinWH **Modbus Bridge**.

Its control endpoints are gated — `POST /api/command` requires the ``control`` capability —
and we sent nothing, so dispatch over REST could never have worked against a secured install
(#56). Worse, availability was probed with an unauthenticated ``GET /api/health``, which a
properly secured bridge answers 200, so the provider reported **ready** for a path that
would 401 on the first command.

Four states, not two, because they need different fixes:

====================  ==========================================================
``unreachable``       nothing answered — host, port, network
``unauthenticated``   it answered, we have no usable session — missing or wrong
                      credentials
``forbidden``         we are logged in and **lack the control capability** — the
                      password is right and the ACCOUNT is wrong. A ``viewer``
                      signs in happily and cannot dispatch.
``ready``             logged in, with ``control``
====================  ==========================================================

``forbidden`` is the one worth the trouble: everything looks configured, login succeeds, and
dispatch still fails. No message about connectivity would ever point at the remedy, which is
a different account.

Capability comes from **their** login response, which carries ``capabilities`` directly. We
do not mirror their role table — it is theirs to change, and a copy here would drift.
"""
from __future__ import annotations

import http.cookiejar
import json
import threading
import urllib.error
import urllib.request
from typing import Any

#: Their capability name for "may operate the battery".
CONTROL_CAPABILITY = "control"

LOGIN_PATH = "/api/auth/login"
WHOAMI_PATH = "/api/auth/me"

_TIMEOUT = 8.0
_lock = threading.Lock()
#: base url -> {"opener", "capabilities"}. One session per bridge, reused across commands:
#: logging in per command would be both slow and noisy in their audit trail.
_sessions: dict[str, dict[str, Any]] = {}


class CommandRejected(RuntimeError):
    """The bridge understood the request and refused it — a 4xx that is not about auth.

    Their PR #100 (fixing their #97) returns **400** for an unknown slug, with the known
    slugs listed in the message. Before that build an unknown slug returned ``ok: true``, so
    this distinguishes "your build rejects it" from "your build silently accepted it", and
    both are better than a raw traceback.
    """


class AuthError(RuntimeError):
    """Could not obtain a usable session. ``state`` is one of the four above."""

    def __init__(self, state: str, message: str):
        super().__init__(message)
        self.state = state


def reset(base: str | None = None) -> None:
    """Drop a cached session (credentials changed, tests)."""
    with _lock:
        if base is None:
            _sessions.clear()
        else:
            _sessions.pop(base.rstrip("/"), None)


def _open(opener, url: str, data: bytes | None = None, timeout: float = _TIMEOUT):
    req = urllib.request.Request(
        url, data=data, method="POST" if data is not None else "GET",
        headers={"Content-Type": "application/json"} if data is not None else {})
    return opener.open(req, timeout=timeout)  # noqa: S310 — user-configured host


def login(base: str, username: str, password: str) -> dict[str, Any]:
    """Establish a session. Returns ``{"opener", "capabilities"}``. Raises :class:`AuthError`."""
    base = base.rstrip("/")
    if not username:
        raise AuthError("unauthenticated", "no Modbus Bridge username configured")
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    body = json.dumps({"username": username, "password": password or ""}).encode()
    try:
        with _open(opener, base + LOGIN_PATH, body) as r:
            payload = json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise AuthError("unauthenticated",
                            f"Modbus Bridge rejected the credentials (HTTP {e.code})") from e
        raise AuthError("unreachable", f"Modbus Bridge login failed (HTTP {e.code})") from e
    except Exception as e:  # noqa: BLE001 — URL error, timeout, DNS
        raise AuthError("unreachable", f"Modbus Bridge unreachable: {e}") from e

    caps = payload.get("capabilities")
    if caps is None:
        caps = (payload.get("user") or {}).get("capabilities") or []
    sess = {"opener": opener, "capabilities": list(caps)}
    with _lock:
        _sessions[base] = sess
    return sess


def session(base: str, username: str, password: str, *, fresh: bool = False) -> dict[str, Any]:
    """A cached session, logging in if needed."""
    base = base.rstrip("/")
    if not fresh:
        with _lock:
            hit = _sessions.get(base)
        if hit:
            return hit
    return login(base, username, password)


def status(base: str, username: str, password: str) -> dict[str, Any]:
    """``{"state", "reason", "capabilities"}`` — what this bridge can actually do for us.

    This is what availability must be measured on. An unauthenticated health check tells us
    the host is up, which is not the question being asked.
    """
    if not base:
        return {"state": "unreachable", "reason": "no Modbus Bridge URL configured",
                "capabilities": []}
    try:
        sess = session(base, username, password)
    except AuthError as e:
        return {"state": e.state, "reason": str(e), "capabilities": []}
    caps = sess["capabilities"]
    if CONTROL_CAPABILITY not in caps:
        return {
            "state": "forbidden",
            "reason": (f"signed in, but this account lacks the '{CONTROL_CAPABILITY}' "
                       f"capability (has: {', '.join(caps) or 'none'}). Use an account that "
                       f"may operate the battery."),
            "capabilities": caps,
        }
    return {"state": "ready", "reason": None, "capabilities": caps}


def post_command(base: str, username: str, password: str, slug: str, value) -> dict[str, Any]:
    """POST one ``/api/command``. Re-logs in once on 401 — sessions expire.

    NB the reply's ``ok`` is **not** a per-call result on their current build (their #97):
    an unknown slug returns ``ok: true``. Callers must confirm a dispatch through
    ``/api/gateways/<id>/dispatch-outcomes``, never from this return value.
    """
    base = base.rstrip("/")
    data = json.dumps({"slug": slug, "value": str(value)}).encode()
    for attempt in (0, 1):
        sess = session(base, username, password, fresh=bool(attempt))
        try:
            with _open(sess["opener"], base + "/api/command", data) as r:
                body = r.read().decode()
            return json.loads(body) if body else {}
        except urllib.error.HTTPError as e:
            if e.code == 401 and attempt == 0:
                continue                      # session expired — log in again, once
            if e.code == 401:
                raise AuthError("unauthenticated", "Modbus Bridge rejected the session") from e
            if e.code == 403:
                raise AuthError(
                    "forbidden",
                    "Modbus Bridge refused the command: this account lacks the "
                    "'control' capability") from e
            if 400 <= e.code < 500:
                detail = ""
                try:
                    detail = (json.loads(e.read().decode() or "{}") or {}).get("detail", "")
                except Exception:  # noqa: BLE001 — the status is the point, not the body
                    pass
                raise CommandRejected(
                    f"Modbus Bridge rejected '{slug}' (HTTP {e.code})"
                    + (f": {detail}" if detail else "")) from e
            raise
    raise AuthError("unauthenticated", "Modbus Bridge login did not produce a usable session")
