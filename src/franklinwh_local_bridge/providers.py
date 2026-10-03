"""Hybrid capability providers — Phase 1: abstraction + detection (no writes yet).

The local sendMqtt API physically cannot do two things (the hard walls in
``docs/API_COMPARISON.md``): **battery dispatch** (force charge/discharge/standby/release,
target-SoC — Modbus) and **cloud-only writes** (reserve SoC, grid limits — Cloud). The
Local Bridge fills them via *providers*, resolved per capability in priority order:

* **dispatch**  → an installed **Modbus Bridge** REST (preferred — its dispatch watchdog is
  proven) → else the **franklinwh-modbus** library (needs an aGate host).
* **reserve**   → an installed **FWHAI** REST (preferred) → else the **franklinwh-cloud**
  library (needs cloud credentials).

This module only *detects and resolves* which provider is available — the actual writes are
Phase 2 (dispatch) and Phase 3 (reserve). Detection never raises and never blocks long
(short-timeout health probe; import check).
"""

from __future__ import annotations

import importlib.util
import json
import urllib.request

from .config import Settings


class DispatchUnavailable(RuntimeError):
    """No dispatch provider is configured/reachable (→ 503)."""


# Local dispatch action → the Modbus Bridge's battery_command value (Phase 2).
_MB_ACTION = {
    "charge": "Force Charge",
    "discharge": "Force Discharge",
    "standby": "Force Standby",
    "release": "Release",
    "stop": "Release",
}

# capability id -> human description (surfaced by /api/providers + the UI later).
CAPABILITIES = {
    "dispatch": "Battery dispatch — force charge / discharge / standby / release, target-SoC",
    "reserve": "Reserve-SoC write + cloud-only settings",
}

_PROBE_TIMEOUT = 3.0


def _probe_url(base: str, path: str = "/api/health", timeout: float = _PROBE_TIMEOUT) -> bool:
    """True if the sibling bridge answers 200 at ``base + path``. Never raises."""
    if not base:
        return False
    url = base.rstrip("/") + path
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:  # noqa: S310 — user-configured host
            return 200 <= getattr(r, "status", r.getcode()) < 300
    except Exception:  # noqa: BLE001 — unreachable / bad URL / timeout ⇒ not available
        return False


def _lib_available(module: str) -> bool:
    """True if a fallback library is importable (without importing it)."""
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def _resolve(capability: str, candidates: list[dict]) -> dict:
    """Pick the first available candidate as ``active``; report all candidates + availability."""
    active = next((c for c in candidates if c.get("available")), None)
    return {
        "capability": capability,
        "description": CAPABILITIES.get(capability, ""),
        "available": active is not None,
        "active": active,
        "candidates": candidates,
    }


def dispatch_provider(s: Settings) -> dict:
    """Resolve the battery-dispatch provider: Modbus Bridge REST → franklinwh-modbus lib."""
    candidates: list[dict] = []
    if s.modbus_bridge_url:
        candidates.append({
            "kind": "modbus-bridge", "via": "rest", "source": s.modbus_bridge_url,
            "available": _probe_url(s.modbus_bridge_url),
        })
    host = s.modbus_host or s.fwh_host
    lib = _lib_available("franklinwh_modbus")
    candidates.append({
        "kind": "modbus-lib", "via": "library",
        "source": (f"{host}:502" if host else ""),
        "available": bool(lib and host),
        "reason": None if (lib and host) else ("library not installed" if not lib else "no aGate host"),
    })
    return _resolve("dispatch", candidates)


def reserve_provider(s: Settings) -> dict:
    """Resolve the reserve-SoC / cloud-write provider: FWHAI REST → franklinwh-cloud lib."""
    candidates: list[dict] = []
    if s.fwhai_url:
        candidates.append({
            "kind": "fwhai", "via": "rest", "source": s.fwhai_url,
            "available": _probe_url(s.fwhai_url),
        })
    lib = _lib_available("franklinwh_cloud")
    creds = bool(s.fwh_cloud_email and s.fwh_cloud_password)
    candidates.append({
        "kind": "cloud-lib", "via": "library", "source": ("cloud" if creds else ""),
        "available": bool(lib and creds),
        "reason": None if (lib and creds) else ("library not installed" if not lib else "no cloud credentials"),
    })
    out = _resolve("reserve", candidates)
    # Auth status (breaker) — the UI enables the reserve editors ONLY when validated. Presence
    # of creds is not enough; ``auth`` reflects a real login check (unknown until validated).
    auth = cloud_auth_status()
    out["auth"] = auth["state"]
    out["auth_error"] = auth["error"]
    # "available" = can we attempt without risking lockout: creds+lib present AND not locked.
    out["available"] = bool(out["available"] and auth["state"] != "locked")
    # "validated" = confirmed working; the write UI keys off this.
    out["validated"] = auth["state"] == "valid"
    return out


def capabilities(s: Settings) -> dict:
    """Full capability report: which hard-wall capabilities are fillable, and by what."""
    return {
        "dispatch": dispatch_provider(s),
        "reserve": reserve_provider(s),
    }


# ── Phase 2: battery dispatch (actuate) ───────────────────────────────────────
def _post_command(base: str, slug: str, value, timeout: float = 8.0) -> dict:
    """POST one Modbus-Bridge ``/api/command`` ``{slug, value}`` (value stringified)."""
    url = base.rstrip("/") + "/api/command"
    data = json.dumps({"slug": slug, "value": str(value)}).encode()
    req = urllib.request.Request(
        url, data=data, method="POST", headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 — user-configured host
        body = r.read().decode()
    return json.loads(body) if body else {}


def _dispatch_via_modbus_bridge(base: str, action: str, power_w, power_pct,
                                duration_s, target_soc) -> dict:
    """Stage power/duration/target-SoC, then trigger the battery_command (the Modbus Bridge
    command model is stateful; the action fires using the staged params). Returns the final
    command reply. The Bridge owns the dispatch **watchdog** — that's why we delegate."""
    staged = []
    if power_w is not None:
        _post_command(base, "battery_command_power", int(power_w)); staged.append(f"{int(power_w)}W")
    elif power_pct is not None:
        _post_command(base, "battery_command_power_pct", int(power_pct)); staged.append(f"{int(power_pct)}%")
    if duration_s is not None:
        _post_command(base, "battery_command_duration", int(duration_s)); staged.append(f"{int(duration_s)}s")
    if target_soc is not None:
        _post_command(base, "battery_command_target_soc", int(target_soc)); staged.append(f"→{int(target_soc)}%")
    final = _post_command(base, "battery_command", _MB_ACTION[action])
    return {"command": _MB_ACTION[action], "staged": staged, "reply": final}


def dispatch(s: Settings, action: str, *, power_w=None, power_pct=None,
             duration_s=None, target_soc=None) -> dict:
    """Actuate battery dispatch (force charge/discharge/standby/release + target-SoC) via
    the resolved provider. Gated upstream by allow_writes. Raises ``DispatchUnavailable``
    (no provider), ``ValueError`` (bad action), ``NotImplementedError`` (library path not
    wired), or a transport error (provider unreachable)."""
    act = (action or "").strip().lower()
    if act not in _MB_ACTION:
        raise ValueError(f"unknown action {action!r}; expected charge/discharge/standby/release")
    prov = dispatch_provider(s)
    if not prov["available"]:
        raise DispatchUnavailable(
            "no dispatch provider — configure modbus_bridge_url (an installed Modbus Bridge) "
            "or the franklinwh-modbus library + modbus_host")
    active = prov["active"]
    if active["kind"] == "modbus-bridge":
        res = _dispatch_via_modbus_bridge(active["source"], act, power_w, power_pct,
                                          duration_s, target_soc)
        return {"ok": True, "action": act, "provider": {"kind": active["kind"],
                "via": active["via"], "source": active["source"]}, "result": res}
    # modbus-lib: dispatch without the Bridge's watchdog is unsafe (orphan-dispatch risk) —
    # not wired in Phase 2. The library path is detected but actuation is deferred.
    raise NotImplementedError(
        "dispatch via the franklinwh-modbus library isn't wired yet (Phase 2b) — install a "
        "Modbus Bridge; its software watchdog is what makes force charge/discharge safe")


# ── Phase 3: reserve-SoC write (cloud-owned) ──────────────────────────────────
class ReserveUnavailable(RuntimeError):
    """No cloud reserve provider is configured/reachable (→ 503)."""


class ReserveLocked(RuntimeError):
    """Cloud auth is circuit-broken after repeated failures — refuse to attempt (→ 423),
    so we never lock the FranklinWH account out. Cleared when credentials change."""


# Circuit breaker for cloud auth. We NEVER retry a failing login in the background and we
# STOP attempting after a few consecutive failures — repeated bad-credential logins can lock
# the FranklinWH account. Reset only when the credentials change (or a manual retry).
_MAX_AUTH_FAILS = 3
_cloud_auth = {"state": "unknown", "fail_count": 0, "error": None, "checked_at": 0.0}

#: Key under which the breaker persists. Held in-process AND on disk: a bare
#: module global resets on restart, so a restart loop would spend three fresh
#: login failures per cycle — exactly the account lockout the breaker exists to
#: prevent. Persisting it means the lock survives; ``reset_cloud_breaker()`` (on
#: a credential change or explicit user retry) is the way out.
_BREAKER_KEY = "_cloud_auth_breaker"

#: Re-check a "valid" credential no more often than this. Revocation and password
#: changes are otherwise only discovered the next time a write is attempted, so a
#: stale "valid" can sit on screen indefinitely.
REVALIDATE_AFTER_S = 12 * 3600

#: A transient failure is retried sooner than a healthy credential is re-checked —
#: "unreachable" is a question we want answered, not a verdict.
RETRY_UNREACHABLE_AFTER_S = 30 * 60

#: Cap on a background re-check so a slow cloud cannot stall device polling. The
#: cloud library allows 30 s per request and validate_cloud makes up to three, so
#: an unbounded call could block a poll cycle for ~90 s.
VALIDATE_TIMEOUT_S = 25.0


_breaker_loaded = False


def _load_breaker() -> None:
    """Restore persisted breaker state into the in-process snapshot. Best-effort.

    Lazy and once-only, rather than at import, so tests that monkeypatch
    ``environment.DATA_DIR`` are not bound to whatever it was at import time.
    """
    global _breaker_loaded
    if _breaker_loaded:
        return
    _breaker_loaded = True
    from .config import load_overrides
    try:
        saved = (load_overrides() or {}).get(_BREAKER_KEY)
    except Exception:  # noqa: BLE001 — never block startup on this
        return
    if not isinstance(saved, dict):
        return
    for key in ("state", "fail_count", "error", "checked_at"):
        if key in saved:
            _cloud_auth[key] = saved[key]


def _save_breaker() -> None:
    """Persist the breaker. Best-effort — losing it only costs a re-check."""
    from .config import save_override_raw
    try:
        save_override_raw(_BREAKER_KEY, dict(_cloud_auth))
    except Exception:  # noqa: BLE001
        pass


def cloud_auth_status() -> dict:
    """Snapshot of the cloud-auth breaker.

    ``state`` is one of unknown / unconfigured / valid / invalid / locked.
    ``checked_at`` is when the last real check ran (0 = never), and ``age_s`` how
    long ago — so a caller can tell "valid 30 seconds ago" from "valid last week".
    ``stale`` marks a ``valid`` that is older than :data:`REVALIDATE_AFTER_S`.
    """
    import time as _t
    _load_breaker()
    out = dict(_cloud_auth)
    checked = out.get("checked_at") or 0
    out["age_s"] = round(_t.time() - checked, 1) if checked else None
    out["stale"] = bool(
        out.get("state") == "valid" and checked
        and (_t.time() - checked) > REVALIDATE_AFTER_S
    )
    out["max_fails"] = _MAX_AUTH_FAILS
    return out


def reset_cloud_breaker() -> None:
    """Clear the breaker so the next attempt is allowed again — call when creds change."""
    _cloud_auth.update(state="unknown", fail_count=0, error=None, checked_at=0.0)
    _save_breaker()


def _note_auth_success() -> None:
    _cloud_auth.update(state="valid", fail_count=0, error=None)


#: Exception names that mean "the credentials were REJECTED" — these count toward
#: the lockout. Anything else (DNS, TLS, 5xx, request timeout, gateway offline) is
#: transient: it must NOT count, or a bad network week would lock the breaker and
#: disable reserve control while reporting "invalid credentials". Matched by name
#: so franklinwh_cloud stays an optional import.
_AUTH_REJECTION_NAMES = frozenset({
    "InvalidCredentialsException", "AccountLockedException", "UauthorizedRequest",
    "TokenExpiredException",
})


def _is_auth_rejection(exc: BaseException) -> bool:
    """True when the cloud actively rejected the credentials.

    Falls back to inspecting the message for an explicit 401/403/unauthorized,
    since the library also raises bare exceptions in places.
    """
    if type(exc).__name__ in _AUTH_REJECTION_NAMES:
        return True
    text = str(exc).lower()
    return any(m in text for m in ("401", "403", "unauthorized", "invalid credential",
                                   "password", "account locked"))


def _note_auth_failure(err: str, *, counts: bool = True) -> None:
    """Record a failed check.

    ``counts=False`` marks it transient — state becomes ``unreachable`` and the
    lockout counter is left alone, so network trouble can never lock the breaker.
    """
    _cloud_auth["error"] = err
    if not counts:
        _cloud_auth["state"] = "unreachable"
        return
    _cloud_auth["fail_count"] += 1
    _cloud_auth["state"] = "locked" if _cloud_auth["fail_count"] >= _MAX_AUTH_FAILS else "invalid"


def revalidate_due(s: Settings) -> bool:
    """Should a background re-check run now?

    Only when credentials are configured, the breaker is not locked, and either we
    have never checked or the last check is older than :data:`REVALIDATE_AFTER_S`.
    Deliberately conservative: a locked breaker is never retried automatically,
    since the point is to protect the account rather than to keep trying.
    """
    import time as _t
    _load_breaker()
    if not (s.fwh_cloud_email and s.fwh_cloud_password):
        return False
    if _cloud_auth.get("state") == "locked":
        return False
    checked = _cloud_auth.get("checked_at") or 0
    window = (RETRY_UNREACHABLE_AFTER_S
              if _cloud_auth.get("state") == "unreachable" else REVALIDATE_AFTER_S)
    return (_t.time() - checked) > window


def _cloud_login_check(email: str, password: str, gateway: str | None) -> None:
    """One login + a permissioned read (get_all_mode_soc) to confirm the creds AND gateway
    access. Raises on any failure. UPPERCASE gateway (the cloud is case-sensitive)."""
    import asyncio
    from franklinwh_cloud.wrapper import FranklinWHCloud
    gw = gateway.upper() if gateway else gateway

    async def _run():
        cloud = FranklinWHCloud(email=email, password=password, gateway=gw)
        await cloud.login()
        if gw:
            await cloud.select_gateway(gw)
            await cloud.get_all_mode_soc()   # proves gateway-level permission, not just login

    asyncio.run(_run())


def validate_cloud(s: Settings) -> dict:
    """Actively check the cloud credentials with ONE attempt, honouring the breaker. Never
    auto-retried in the background — only called on explicit user action / a single lazy
    check. Returns the auth status snapshot. This is the lockout guard: after
    ``_MAX_AUTH_FAILS`` consecutive failures the breaker opens and we stop attempting until
    the credentials change."""
    _load_breaker()
    if not (s.fwh_cloud_email and s.fwh_cloud_password):
        _cloud_auth.update(state="unconfigured", error=None)
        return cloud_auth_status()
    if _cloud_auth["state"] == "locked":
        return cloud_auth_status()   # refuse to attempt — protects the account
    try:
        _cloud_login_check(s.fwh_cloud_email, s.fwh_cloud_password, s.fwh_cloud_gateway or None)
        _note_auth_success()
    except Exception as e:  # noqa: BLE001 — any auth/permission/transport failure
        _note_auth_failure(str(e) or type(e).__name__,
                           counts=_is_auth_rejection(e))
    import time as _t
    _cloud_auth["checked_at"] = _t.time()
    _save_breaker()
    return cloud_auth_status()


# Mode name/alias → cloud workMode (TOU=1, Self=2, Backup=3). Resolve by NAME, never reuse
# a local index — see the mode-index memory.
_RESERVE_WORKMODE = {
    "self": 2, "self-consumption": 2,
    "tou": 1, "time-of-use": 1,
    "backup": 3, "emergency backup": 3, "emergency-backup": 3,
}


def _cloud_set_reserve(email: str, password: str, gateway: str | None,
                       work_mode: int, soc: int) -> dict:
    """Run the async franklinwh-cloud ``updateSocV2`` write. Snapshots the prior per-mode
    reserve first (reversibility — see the record-prior-state memory), then writes. Runs its
    own event loop (called from the sync endpoint threadpool)."""
    import asyncio
    from franklinwh_cloud.wrapper import FranklinWHCloud

    # The cloud is case-sensitive on the gateway serial — it must be UPPERCASE, or the API
    # replies code 181 "Operation without permission". Local logs/ini often carry lowercase.
    gw = gateway.upper() if gateway else gateway

    async def _run():
        cloud = FranklinWHCloud(email=email, password=password, gateway=gw)
        await cloud.login()
        if gw:
            await cloud.select_gateway(gw)
        prior = None
        try:
            allsoc = await cloud.get_all_mode_soc()
            prior = next((m for m in allsoc if m.get("workMode") == work_mode), None)
        except Exception:  # noqa: BLE001 — prior snapshot is best-effort
            prior = None
        res = await cloud.update_soc(requestedSOC=soc, workMode=work_mode, electricityType=1)
        return {"cloud": res, "prior": prior}

    return asyncio.run(_run())


def set_reserve(s: Settings, mode: str, soc) -> dict:
    """Set a mode's reserve SoC via the CLOUD provider — the local API silently discards this
    write (it's cloud-owned; see the reserve memory), so this is the only path that sticks.
    Gated upstream by allow_writes. Raises ``ReserveUnavailable`` (no provider), ``ValueError``
    (bad mode/soc), ``NotImplementedError`` (FWHAI path not wired), or a transport error."""
    act = (mode or "").strip().lower()
    wm = _RESERVE_WORKMODE.get(act)
    if wm is None:
        raise ValueError(f"unknown mode {mode!r}; expected self / tou / backup")
    try:
        soc_i = int(soc)
    except (TypeError, ValueError):
        raise ValueError("soc must be an integer percent")
    if not 0 <= soc_i <= 100:
        raise ValueError("soc must be between 0 and 100")

    # Circuit breaker: if repeated logins have failed, refuse — never risk locking the account.
    if _cloud_auth["state"] == "locked":
        raise ReserveLocked(
            "cloud sign-in is temporarily disabled after repeated failures — re-enter your "
            "FranklinWH credentials to try again")

    prov = reserve_provider(s)
    cands = prov.get("candidates", [])
    # Prefer the cloud LIBRARY for the write (it's the proven updateSocV2 path), regardless of
    # the display preference that puts FWHAI-REST first.
    cloud = next((c for c in cands if c["kind"] == "cloud-lib" and c.get("available")), None)
    if cloud:
        try:
            out = _cloud_set_reserve(s.fwh_cloud_email, s.fwh_cloud_password,
                                     s.fwh_cloud_gateway or None, wm, soc_i)
        except Exception as e:  # noqa: BLE001 — feed the breaker so bad creds don't hammer cloud
            _note_auth_failure(str(e) or type(e).__name__)
            raise
        _note_auth_success()   # a successful write proves the creds are good
        return {"ok": True, "mode": act, "workMode": wm, "requested_soc": soc_i,
                "prior": out.get("prior"),
                "provider": {"kind": "cloud-lib", "via": "library"},
                "result": out.get("cloud"),
                "note": "reserve is cloud-owned; the aGate / local mode_list reflects it within ~8s"}
    fwhai = next((c for c in cands if c["kind"] == "fwhai" and c.get("available")), None)
    if fwhai:
        raise NotImplementedError(
            "reserve write via FWHAI REST isn't wired yet (Phase 3b) — configure cloud "
            "credentials (fwh_cloud_email/password) to use the franklinwh-cloud path")
    raise ReserveUnavailable(
        "no reserve provider — set fwh_cloud_email / fwh_cloud_password (+ fwh_cloud_gateway) "
        "or install FWHAI; reserve SoC cannot be set over the local API")
