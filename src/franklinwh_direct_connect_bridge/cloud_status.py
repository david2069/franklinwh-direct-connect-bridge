"""Authoritative VPP / operating-mode from the FranklinWH Cloud API (franklinwh-cloud).

The local direct-connect AND Modbus APIs only ever see a FORCE dispatch (M704 WSet) — they
cannot tell a genuine VPP from a local force_charge. The cloud ``get_stats()`` carries the real
truth: ``effective_mode`` (the app-matching label) and VPP == ``run_status==9 or tou_mode==9``.
``get_programme_info()`` names the enrolled programme (partner) for the badge tooltip.

This module reads that on a SLOW cadence, REUSING the ``providers`` auth breaker so a bad login
can never lock the account. On a transport error it marks the breaker "unreachable" (never
counts toward lockout) and the caller falls back to the Modbus FORCE signal.
"""
from __future__ import annotations

import logging
import time

from .config import Settings
from . import providers

log = logging.getLogger(__name__)

#: Last transport/auth error from a cloud read, for the status loop's failure message
#: (poll() swallows the exception and returns None so the loop stays alive).
LAST_ERROR: str | None = None

#: One logged-in ``PasswordAuth`` per credential pair, reused across passes (#233). The
#: token lives in the auth object and the library's Client refreshes it itself on a 401 /
#: 10009, so a pass needs no login. New credentials are a new key, so a password change
#: logs in afresh. The httpx session is NOT reused: it is bound to the event loop each
#: pass creates, so every pass builds a fresh Client on the shared auth.
_AUTH: dict[tuple[str, str], object] = {}
LOGINS = 0          # logins made by this process, for tests and diagnostics
#: (login, requested serial) -> the serial resolve_gateway chose for it.
_SERIAL: dict[tuple, str] = {}


#: The longest wait between failed passes, in seconds.
MAX_BACKOFF_S = 1800


def retry_delay(interval: int, failures: int) -> int:
    """Seconds to wait after ``failures`` consecutive failed passes (#233).

    Never below the poll interval (it used to retry every 45 s, which polled a rate-limited
    account harder), doubling per failure up to 8x, and capped at 30 min."""
    return min(int(interval) * 2 ** min(max(failures, 1), 3), MAX_BACKOFF_S)


class _LoginFailed(Exception):
    """Carries the library's login exception out of the event loop, untouched."""

    def __init__(self, original: BaseException):
        super().__init__(str(original))
        self.original = original


async def _auth_for(email: str, password: str, source: str = "status"):
    """The shared, logged-in auth for these credentials (one login per process).
    Every real login is guarded by the account hold and audited."""
    global LOGINS
    from franklinwh_cloud.auth import PasswordAuth
    key = (email, password)
    auth = _AUTH.get(key)
    if auth is None:
        auth = PasswordAuth(email, password)
        _AUTH.clear()            # only the current credentials are ever kept
        _AUTH[key] = auth
    if not (getattr(auth, "info", None) or {}).get("token"):
        providers.guard_login(email, source)        # raises while the hold is on
        LOGINS += 1
        try:
            await auth.get_token()
        except Exception as e:  # noqa: BLE001
            providers.note_login_result(email, source, e)
            raise
        providers.note_login_result(email, source, None)
    return auth


# Cloud run_status / tou_mode that means a VPP dispatch is running.
_VPP_ID = 9
#: Cloud reads older than this are treated as stale — the UI falls back to the live Modbus
#: FORCE signal rather than trusting a minutes-old cloud VPP state.
STALE_AFTER_S = 900


async def _client_for(email: str, password: str, gateway: str | None, source: str = "status"):
    """A franklinwh-cloud ``Client`` on the shared login, bound to the aGate the library's
    ``resolve_gateway`` chooses: the given serial (verified on the account) or the account's
    only aGate. Several and no serial -> ``GatewaySelectionError``; it never guesses (#248).
    Use as ``async with``; the library closes its httpx session on exit."""
    from franklinwh_cloud import resolve_gateway
    from franklinwh_cloud.client import Client
    auth = await _auth_for(email, password, source)
    # resolve_gateway lists the account's aGates on every call; the answer cannot change
    # under one login, so ask once per login rather than adding a request to every pass.
    key = (id(auth), (gateway or "").strip().upper())
    serial = _SERIAL.get(key)
    if serial is None:
        serial = await resolve_gateway(auth, gateway)
        _SERIAL.clear()
        _SERIAL[key] = serial
    return Client(auth, serial)


def _read_sync(email: str, password: str, gateway: str | None) -> tuple:
    """One authenticated cloud read: (current, programmes). Runs its own event loop (called
    from a worker thread). UPPERCASE gateway — the cloud is case-sensitive on the serial."""
    import asyncio

    async def _run():
        async with await _client_for(email, password, gateway) as cloud:
            stats = await cloud.get_stats()
            prog = []
            try:
                prog = await cloud.get_programme_info()   # best-effort; shape varies
            except Exception:  # noqa: BLE001 — the programme name is a nice-to-have
                prog = []
            edge = None
            try:
                edge = (cloud.get_metrics() or {}).get("edge")   # CloudFront PoP snapshot
            except Exception:  # noqa: BLE001 — edge metrics are a nice-to-have
                edge = None
            return stats.current, prog, edge

    return asyncio.run(_run())


def verify_credentials(email: str, password: str, gateway: str | None = None) -> dict:
    """Try a real cloud login and settle which aGate to use.
    ``{"ok": bool, "detail": str, "gateways": [...], "gateway": str | None}``.

    A LOGIN, not a format check: the only thing that establishes whether an account works
    is the account working. The serial is optional for the login but every gateway call
    needs the right one (owner, 2026-10-21, #248): a typed serial must belong to this
    account; with none, an account with one aGate uses it and one with several is asked
    to choose. Credentials are never stored here; the caller stores only what came back ok.

    Never raises: a wrong password, an unreachable cloud and a missing library are all
    answers the user needs to see, not exceptions.
    """
    if not (email and password):
        return {"ok": False, "detail": "Email and password are both needed."}
    try:
        import asyncio

        from franklinwh_cloud import resolve_gateway
        from franklinwh_cloud.auth import PasswordAuth
        from franklinwh_cloud.exceptions import GatewaySelectionError
    except ImportError:
        return {"ok": False,
                "detail": "The franklinwh-cloud library is not installed in this build, "
                          "so cloud features are unavailable regardless of credentials."}
    want = gateway.strip() if gateway else None

    try:
        providers.guard_login(email, "credential check")
    except providers.CloudLoginHeld as e:
        return {"ok": False, "held": True, "detail": str(e)}

    async def _run():
        global LOGINS
        auth = PasswordAuth(email, password)
        LOGINS += 1
        try:
            await auth.get_token()                  # a fresh login: this IS the test
        except Exception as e:  # noqa: BLE001
            providers.note_login_result(email, "credential check", e)
            raise _LoginFailed(e) from e
        providers.note_login_result(email, "credential check", None)
        _AUTH.clear()
        _AUTH[(email, password)] = auth              # the poller reuses this login
        # The library chooses the aGate: the typed serial if the account has it, or the
        # account's only one; never one of several (#248).
        return await resolve_gateway(auth, want)

    try:
        chosen = asyncio.run(_run())
    except _LoginFailed as lf:
        e = lf.original
        # FranklinWH's own words, unedited: "Incorrect password, you still have 2 chances",
        # "The password is locked. Please try again after …". A rejection has already put
        # the account on hold (providers.note_login_result).
        msg = str(e) or type(e).__name__
        held = providers.cloud_hold()["active"]
        return {"ok": False, "rejected": providers._is_auth_rejection(e), "held": held,
                "detail": f"FranklinWH: {msg}" + (" — cloud sign-in is now on hold; check "
                          "the password in the FranklinWH app before clearing it." if held else "")}
    except GatewaySelectionError as e:
        return {"ok": False, "gateways": list(getattr(e, "serials", []) or []), "gateway": None,
                "detail": f"Signed in. {e}"}
    except Exception as e:  # noqa: BLE001 — after the login: choosing the aGate
        log.info("cloud credential check failed after login: %s: %s", type(e).__name__, e)
        return {"ok": False, "detail": f"{type(e).__name__}: {e}"}
    return {"ok": True, "gateways": [chosen], "gateway": chosen,
            "detail": f"Signed in to the FranklinWH cloud; using aGate {chosen}."}


def read_power_control(email: str, password: str, gateway: str | None) -> dict:
    """One authenticated cloud read of the GLOBAL grid power-control caps
    (globalGridChargeMax / globalGridDischargeMax, -1=unlimited) — used as an independent
    WITNESS when cross-checking a local 1701 grid-limit write. NB this is a DIFFERENT storage
    plane: the cloud globals do not necessarily reflect a local 1701 change (proven not to
    sync), so treat it as context, not proof. Runs its own event loop; never raises."""
    import asyncio

    async def _run():
        async with await _client_for(email, password, gateway, "power-control read") as cloud:
            return await cloud.get_power_control_settings()

    return asyncio.run(_run())


def _programme_label(prog) -> str | None:
    """Best-effort programme/partner name from get_programme_info(). The shape VARIES: a list
    (of strings or dicts), OR a single DICT (the VPP programme object with
    programName/partnerName/... keys). Iterating a dict yields its KEYS — which dumped
    "programId · programName · ..." into the run-status badge; extract the name field instead."""
    def _name(d):
        return d.get("partnerName") or d.get("programName") or d.get("name")
    names: list[str] = []
    if isinstance(prog, dict):
        n = _name(prog)
        if n:
            names.append(str(n))
    else:
        for p in prog or []:
            try:
                if isinstance(p, str):
                    if p.strip():
                        names.append(p.strip())
                elif isinstance(p, dict):
                    n = _name(p)
                    if n:
                        names.append(str(n))
            except Exception:  # noqa: BLE001
                continue
    return " · ".join(dict.fromkeys(names)) or None


def poll(s: Settings) -> dict | None:
    """One cloud read of the run-status / VPP truth, honouring the breaker. Returns None when
    credentials are absent, the breaker is locked, or the read fails. On success marks the
    breaker valid; on a transport failure marks it unreachable (never counts toward lockout);
    only a real auth rejection counts."""
    if not (s.fwh_cloud_email and s.fwh_cloud_password):
        return None
    providers._load_breaker()
    if providers._cloud_auth.get("state") == "locked":
        return None
    global LAST_ERROR
    _t0 = time.monotonic()
    try:
        cur, prog, edge = _read_sync(s.fwh_cloud_email, s.fwh_cloud_password,
                                     s.fwh_cloud_gateway or None)
    except providers.CloudLoginHeld as e:
        # Refused locally: no request was sent, so the breaker is not touched.
        LAST_ERROR = str(e)
        return None
    except Exception as e:  # noqa: BLE001 — feed the breaker; transport ≠ auth failure
        providers._note_auth_failure(str(e) or type(e).__name__,
                                     counts=providers._is_auth_rejection(e))
        providers._cloud_auth["checked_at"] = time.time()
        providers._save_breaker()
        LAST_ERROR = f"{type(e).__name__}: {e}"
        # DEBUG here (full-trace at debug level); the status LOOP raises the first failure
        # + recovery to WARNING/INFO so a down cloud is visible without 5-min spam.
        log.debug("cloud call failed: get_stats — %s", LAST_ERROR)
        return None
    LAST_ERROR = None
    log.debug("cloud call ok: get_stats + programme + metrics (%d ms)",
              (time.monotonic() - _t0) * 1000)

    # Persist the CloudFront PoP edge for the Network tab's drill-down (best-effort).
    try:
        from . import db, cloud_pop
        cloud_pop.ingest(db.get_store(s), edge)
    except Exception:  # noqa: BLE001
        pass

    providers._note_auth_success()
    providers._cloud_auth["checked_at"] = time.time()
    providers._save_breaker()

    run_status = int(getattr(cur, "run_status", 0) or 0)
    tou_mode = int(getattr(cur, "tou_mode", 0) or 0)
    is_vpp = run_status == _VPP_ID or tou_mode == _VPP_ID
    return {
        "is_vpp": is_vpp,
        "effective_mode": getattr(cur, "effective_mode", "") or "",
        "run_status": run_status,
        "run_status_desc": getattr(cur, "run_status_desc", "") or "",
        "tou_mode": tou_mode,
        "programme": _programme_label(prog) if is_vpp else None,
        "ts": time.time(),
    }
