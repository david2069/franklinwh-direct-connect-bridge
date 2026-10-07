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

_VPP_ID = 9
#: Cloud reads older than this are treated as stale — the UI falls back to the live Modbus
#: FORCE signal rather than trusting a minutes-old cloud VPP state.
STALE_AFTER_S = 900


def _read_sync(email: str, password: str, gateway: str | None) -> tuple:
    """One authenticated cloud read: (current, programmes). Runs its own event loop (called
    from a worker thread). UPPERCASE gateway — the cloud is case-sensitive on the serial."""
    import asyncio
    from franklinwh_cloud.wrapper import FranklinWHCloud
    gw = gateway.upper() if gateway else gateway

    async def _run():
        cloud = FranklinWHCloud(email=email, password=password, gateway=gw)
        await cloud.login()
        if gw:
            await cloud.select_gateway(gw)
        stats = await cloud.get_stats()
        prog = []
        try:
            prog = await cloud.get_programme_info()   # best-effort; shape varies
        except Exception:  # noqa: BLE001 — the programme name is a nice-to-have, not required
            prog = []
        edge = None
        try:
            edge = (cloud.get_metrics() or {}).get("edge")   # CloudFront PoP snapshot for this poll
        except Exception:  # noqa: BLE001 — edge metrics are a nice-to-have
            edge = None
        return stats.current, prog, edge

    return asyncio.run(_run())


def read_power_control(email: str, password: str, gateway: str | None) -> dict:
    """One authenticated cloud read of the GLOBAL grid power-control caps
    (globalGridChargeMax / globalGridDischargeMax, -1=unlimited) — used as an independent
    WITNESS when cross-checking a local 1701 grid-limit write. NB this is a DIFFERENT storage
    plane: the cloud globals do not necessarily reflect a local 1701 change (proven not to
    sync), so treat it as context, not proof. Runs its own event loop; never raises."""
    import asyncio
    from franklinwh_cloud.wrapper import FranklinWHCloud
    gw = gateway.upper() if gateway else gateway

    async def _run():
        cloud = FranklinWHCloud(email=email, password=password, gateway=gw)
        await cloud.login()
        if gw:
            await cloud.select_gateway(gw)
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
