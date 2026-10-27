"""Direct-Modbus battery force control.

Reuses the proven ``franklinwh-modbus`` library (``FranklinWHController`` + WSet
Model 704) to drive the aGate's power setpoint directly over Modbus TCP —
independent of the modbus-bridge SERVICE. Force writes MOVE the battery, so the
library's software ``duration_s`` timer is the only safety on this firmware
(hardware WSetRvrtTms is cosmetic); always release when done.
"""
from __future__ import annotations

import logging
import threading
import time

log = logging.getLogger(__name__)

MODBUS_PORT = 502
UNIT_ID = 2  # FranklinWH default (per the library)

# In-memory record of the dispatch WE started, so the bridge owns the watchdog +
# a global Release, independent of any per-request Modbus connection.
_active: dict = {}            # {command, watts, host, started, duration_s, target_soc, key}
_lock = threading.Lock()
_stop = threading.Event()     # woken on any dispatch change to end old watchdog loops
_soc_getter = None            # callable() -> current SoC %, injected by the endpoint
_on_event = None              # callable(status, detail) -> persist to the activity log


def current() -> dict:
    """The dispatch this bridge is holding (fast; no Modbus). Empty = Not Active."""
    with _lock:
        if not _active:
            return {"active": "Not Active"}
        rem = None
        if _active.get("duration_s"):
            rem = max(0, int(_active["duration_s"] - (time.time() - _active["started"])))
        return {"active": _active["command"], "watts": _active.get("watts"),
                "duration_s": _active.get("duration_s"),
                "target_soc": _active.get("target_soc"), "remaining_s": rem}


def holds_force(*hosts) -> bool:
    """True when this bridge is holding a force on one of ``hosts`` (fast; no Modbus).
    The dashboard shows FORCE only for these; any other remote controller is VPP (#333)."""
    with _lock:
        held = _host_part(_active.get("host")) if _active else ""
    return bool(held) and held in {_host_part(h) for h in hosts if h}


def _fire(status: str, detail: str) -> None:
    if _on_event:
        try:
            _on_event(status, detail)
        except Exception:                                       # noqa: BLE001
            pass


def _release_now(host: str, reason: str) -> None:
    try:
        c, _ = _connect(host)
        try:
            c.reset_control_state()
        finally:
            _close(c)
    except Exception as e:                                       # noqa: BLE001
        log.error("battery force auto-release FAILED (%s): %s", reason, e)
    with _lock:
        _active.clear()
    log.warning("battery force: released (%s)", reason)
    _fire("dispatch-end", f"released — {reason}")


def _watchdog_loop(host: str, key: float, duration_s: int, target_soc: int, watts) -> None:
    """Enforce Duration AND Target SoC (charge stops at SoC>=target, discharge at
    SoC<=target). SoC comes from the poller's cache via _soc_getter — no extra
    Modbus read. Ends the moment a newer command supersedes this one.

    Beats the ``dispatch-watchdog`` worker while a force is active and parks it as
    PAUSED when it ends, so an idle watchdog is never reported as failed (#93)."""
    try:
        _beat(running=True)
        _watch(host, key, duration_s, target_soc, watts)
    finally:
        with _lock:
            idle = _active.get("key") in (None, key)
        if idle:
            _beat(running=False)


def _beat(*, running: bool) -> None:
    try:
        from .workers import registry, WorkerState
        registry.beat("dispatch-watchdog",
                      state=WorkerState.RUNNING if running else WorkerState.PAUSED,
                      detail="force active" if running else "no force active")
    except Exception:  # noqa: BLE001 — observing must never break enforcing
        pass


def _watch(host: str, key: float, duration_s: int, target_soc: int, watts) -> None:
    while not _stop.wait(5.0):
        _beat(running=True)
        with _lock:
            if _active.get("key") != key:
                return
            started = _active["started"]
        if duration_s and (time.time() - started) >= duration_s:
            _release_now(host, f"duration {duration_s}s reached"); return
        if target_soc and _soc_getter:
            try:
                soc = _soc_getter()
            except Exception:                                   # noqa: BLE001
                soc = None
            if soc is not None:
                if watts > 0 and soc >= target_soc:
                    _release_now(host, f"target reached (SoC {soc}% ≥ {target_soc}%)"); return
                if watts < 0 and soc <= target_soc:
                    _release_now(host, f"target reached (SoC {soc}% ≤ {target_soc}%)"); return


def _arm_watchdog(host: str, command: str, watts, duration_s: int, target_soc: int) -> None:
    with _lock:
        key = time.monotonic()
        _active.clear()
        _active.update({"command": command, "watts": watts, "host": host,
                        "started": time.time(), "duration_s": int(duration_s or 0),
                        "target_soc": int(target_soc or 0), "key": key})
    _stop.set(); _stop.clear()        # end any prior loop, then let the new one run
    t = threading.Thread(target=_watchdog_loop,
                         args=(host, key, int(duration_s or 0), int(target_soc or 0), watts),
                         daemon=True)
    t.start()


def _clear_active() -> None:
    with _lock:
        _active.clear()
    _stop.set(); _stop.clear()


def release_stale(host: str) -> dict:
    """On startup: if a force is still enabled on the aGate (e.g. after a crash),
    release it so a dispatch is never left pinned. Best-effort, never raises."""
    try:
        st = status(host)
    except Exception as e:                                       # noqa: BLE001
        return {"released": False, "reason": str(e)}
    if st.get("available") and st.get("active") not in (None, "Not Active"):
        log.warning("battery force: stale %s on boot — releasing", st["active"])
        out = execute("Release", host=host)
        return {"released": bool(out.get("ok")), "was": st["active"]}
    return {"released": False}


def _hhmm(ts) -> str:
    try:
        return time.strftime("%H:%M", time.localtime(float(ts)))
    except Exception:                                           # noqa: BLE001
        return "?"


def reconcile_interrupted(store, host: str, policy: str, *, soc_getter=None,
                          on_event=None, notify=None) -> list[dict]:
    """On boot, reconcile scheduled dispatches the DB still marks 'active' — i.e. a
    force a bridge restart interrupted before a clean release — per the user's policy:

      * none    — record it; no alert, no battery action.
      * notify  — alert the user's devices; never touch the battery (two-masters safe).
      * release — if the window has ended and the battery is still forced, RELEASE; if
                  still inside the window, re-arm the watchdog so it releases at window
                  end (never kills a still-valid dispatch, never re-forces).
      * resume  — like release, plus: if the battery is no longer forced and the window
                  is still open, RE-FORCE for the remaining time.

    Returns a list of {name, action, detail}. Never raises. Only release/resume ever
    command the battery.
    """
    global _soc_getter, _on_event
    if soc_getter is not None:
        _soc_getter = soc_getter
    if on_event is not None:
        _on_event = on_event
    policy = (policy or "notify").lower()
    try:
        rows = store.active_dispatches(host=host)
    except Exception as e:                                       # noqa: BLE001
        return [{"action": "error", "detail": str(e)}]
    if not rows:
        return []
    try:
        st = status(host)
    except Exception as e:                                       # noqa: BLE001
        st = {"available": False, "reason": str(e)}
    forced = bool(st.get("vpp_active"))
    now = time.time()
    results: list[dict] = []
    for d in rows:
        name = d.get("name") or d.get("schedule_id") or "dispatch"
        sid = d.get("schedule_id") or "_batt"
        end_ts = d.get("window_end_ts") or 0
        ended = (now >= end_ts) if end_ts else True
        remaining = max(0, int(end_ts - now)) if end_ts else 0
        when = f"window ended {_hhmm(end_ts)}" if ended else f"window ends {_hhmm(end_ts)}"
        watts = int(d.get("watts") or 0)
        tgt = int(d.get("target_soc") or 0)
        cmd = ("Force Charge" if watts > 0 else
               "Force Discharge" if watts < 0 else "Force Standby")
        action, detail = "recorded", ""

        if policy == "none":
            store.end_dispatch(d["id"], status="interrupted")
            action = "recorded"
            detail = f"'{name}' interrupted ({when}); policy=none — no action."

        elif policy == "notify":
            store.end_dispatch(d["id"], status="interrupted")
            action = "notified"
            detail = (f"Scheduled dispatch '{name}' was interrupted by a bridge restart "
                      f"({when}). Battery is {'STILL FORCED' if forced else 'not forced'}. "
                      f"No automatic action (policy=notify).")

        elif policy in ("release", "resume"):
            if forced and ended:
                execute("Release", host=host)
                store.end_dispatch(d["id"], status="released")
                action = "released"
                detail = f"'{name}' {when}; battery was still forced — RELEASED (policy={policy})."
            elif forced and not ended:
                _arm_watchdog(host, current().get("active") or cmd, watts, remaining, tgt)
                store.record_dispatch(
                    schedule_id=d.get("schedule_id"), name=name, gateway_id=d.get("gateway_id"),
                    host=host, direction=d.get("direction"), watts=watts,
                    power_mode=d.get("power_mode") or "w",
                    target_soc=tgt, window_start_ts=now, window_end_ts=end_ts)
                action = "re-armed"
                detail = (f"'{name}' still forced; re-armed auto-release for the remaining "
                          f"{remaining // 60} min ({when}) (policy={policy}).")
            elif policy == "resume" and not ended:
                pmode = (d.get("power_mode") or "w")
                r = (execute(cmd, host=host, power_pct=abs(watts), power_mode="pct",
                             duration_s=remaining, target_soc=tgt) if pmode == "pct"
                     else execute(cmd, host=host, power_w=abs(watts), power_mode="w",
                                  duration_s=remaining, target_soc=tgt))
                if r.get("ok"):
                    store.end_dispatch(d["id"], status="resumed")
                    store.record_dispatch(
                        schedule_id=d.get("schedule_id"), name=name, gateway_id=d.get("gateway_id"),
                        host=host, direction=d.get("direction"), watts=watts,
                        power_mode=d.get("power_mode") or "w",
                        target_soc=tgt, window_start_ts=now, window_end_ts=end_ts)
                    action = "resumed"
                    detail = (f"'{name}' RESUMED for the remaining {remaining // 60} min "
                              f"({when}); {r.get('result','')}")
                else:
                    store.end_dispatch(d["id"], status="interrupted")
                    action = "resume-failed"
                    detail = f"'{name}' resume FAILED ({when}): {r.get('result','')}"
            else:
                store.end_dispatch(d["id"], status="interrupted")
                action = "cleared"
                detail = (f"'{name}' interrupted; battery no longer forced ({when}) — "
                          f"nothing to do (policy={policy}).")
        else:
            store.end_dispatch(d["id"], status="interrupted")
            action = "recorded"
            detail = f"'{name}' interrupted ({when}); unknown policy '{policy}'."

        try:
            store.log_schedule_event(sid, f"Battery dispatch (reconcile)", action, detail)
        except Exception:                                       # noqa: BLE001
            pass
        if notify and policy != "none" and action != "recorded":
            try:
                notify(f"FranklinWH — scheduled dispatch {action}", detail)
            except Exception:                                   # noqa: BLE001
                pass
        results.append({"name": name, "action": action, "detail": detail})
    return results


def _lib():
    """Import the library lazily so a bridge without it still runs (feature off)."""
    from franklinwh_modbus import BatteryCommand
    from franklinwh_modbus.controller import FranklinWHController
    return FranklinWHController, BatteryCommand


#: User master switch for the Modbus client (this bridge) — ratings AND force dispatch.
#: Toggled from the Control tab (persisted as the ``modbus_enabled`` config); applied at
#: startup. Default OFF (#88): a new install opts in; an existing one keeps its setting
#: (app._modbus_client_enabled). When off, ``available()`` reports disabled and every
#: caller falls back (ratings → user constant; dispatch → 503).
_ENABLED = False


def set_enabled(on: bool) -> None:
    global _ENABLED
    _ENABLED = bool(on)


def is_enabled() -> bool:
    return _ENABLED


def available() -> tuple[bool, str]:
    if not _ENABLED:
        return False, "This bridge's Modbus client is off (Control → Modbus client); the aGate's Modbus TCP Server is not affected"
    try:
        _lib()
    except Exception as e:                                       # noqa: BLE001
        return False, f"franklinwh-modbus library not installed ({type(e).__name__})"
    return True, ""


#: Optional persisted host/port override (Control tab). Blank host = auto-derive from the
#: gateway. Applied centrally in effective_target so EVERY Modbus path (ratings via the
#: scheduler tick, force dispatch, VPP monitor) honours it, not just the API endpoints.
_HOST_OVERRIDE = ""     # host part only (no port)
_PORT_OVERRIDE = 0      # 0 = use MODBUS_PORT


def set_host_override(host: str = "", port: int = 0) -> None:
    """Set the Modbus host/port override. A host may itself carry ``:port`` (that wins);
    a blank host clears the override (back to auto-derive from the gateway)."""
    global _HOST_OVERRIDE, _PORT_OVERRIDE
    from .client import _split_hostport
    host = (host or "").strip()
    if not host:
        _HOST_OVERRIDE, _PORT_OVERRIDE = "", 0
        return
    h, p = _split_hostport(host, port or MODBUS_PORT)
    _HOST_OVERRIDE = h
    _PORT_OVERRIDE = p if (":" in host or port) else 0


def host_override() -> dict:
    """The persisted override, for display/persistence. ``port`` None = default 502."""
    return {"host": _HOST_OVERRIDE, "port": _PORT_OVERRIDE or None}


def effective_target(host: str | None) -> tuple:
    """The (host, port) actually used for Modbus: the override when set, else the passed
    gateway host split into (host, port) — so a mock's ``127.0.0.1:<ephemeral>`` is handled
    and a bare IP keeps the default 502. This is the single source of truth for the target."""
    from .client import _split_hostport
    if _HOST_OVERRIDE:
        return _HOST_OVERRIDE, (_PORT_OVERRIDE or MODBUS_PORT)
    h, p = _split_hostport(host or "", MODBUS_PORT)
    return h, p


def _no_connect_writes(c) -> None:
    """Stop the library writing to the aGate as a side effect of connecting (#224).

    franklinwh-modbus 0.9.5 ``connect()`` runs ``_test_extension_writability()``, which
    writes a test value to 15507 OnGridMode, 15508 SelfReserve and 15509 TOUReserve and
    then restores the original, on EVERY connect. Where those registers are writable, a
    connect would switch the mode and reserves, and leave them wrong if the restore never
    arrived. This bridge connects for every force, release and availability check, so the
    test is replaced on the instance with one that writes nothing. Harmless on a library
    version that no longer runs it.
    """
    def _skipped():
        return {"skipped": "write test disabled by franklinwh-direct-connect-bridge (#224)"}
    c._test_extension_writability = _skipped


def _host_part(host: str | None) -> str:
    from .client import _split_hostport
    return _split_hostport(host or "", MODBUS_PORT)[0]


def is_mock_target(host: str | None) -> bool:
    """True when ``host`` is a mock gateway's, which has no Modbus to reach (#95).

    Matched on the full host and on its host part, because some callers pass the host
    without its port. A host part shared with a real gateway (an emulator on 127.0.0.1)
    is not treated as a mock. An explicit Modbus host override always wins: the user
    pointed the client somewhere real."""
    if not host or _HOST_OVERRIDE:
        return False
    try:
        from . import state
        gws = state.gateways()
    except Exception:                                           # noqa: BLE001
        return False
    hp = _host_part(host)
    mock_hosts, real_parts = set(), set()
    for gw in gws:
        hosts = {h for h in (gw.active_host, gw.configured_host) if h}
        if gw.is_mock:
            mock_hosts |= hosts
        else:
            real_parts |= {_host_part(h) for h in hosts}
    if host in mock_hosts:
        return True
    return hp in {_host_part(h) for h in mock_hosts} and hp not in real_parts


MOCK_REASON = "a mock gateway has no Modbus TCP Server to reach"

#: The outcome of the last REAL connection per target host (#221, #223). Status and
#: reachability are read from here, so showing them never opens a socket.
#: host part -> {"state", "reachable", "ts", "source", "reason"}
_LAST: dict[str, dict] = {}


def _record(host: str | None, state: str, source: str, reason: str = "") -> None:
    eff_host, _ = effective_target(host)
    if not eff_host:
        return
    _LAST[eff_host] = {"state": state, "source": source, "reason": reason,
                       # The socket opened in both of these; "ready" also means SunSpec
                       # answered. This is what modbus_502 has always meant.
                       "reachable": state in ("ready", "no_sunspec"),
                       "ts": time.time()}


def last_result(host: str | None) -> dict | None:
    """The last real connection's outcome for this target, or None if none was made."""
    eff_host, _ = effective_target(host)
    hit = _LAST.get(eff_host) if eff_host else None
    return dict(hit) if hit else None


def _connect(host: str):
    FranklinWHController, BatteryCommand = _lib()
    eff_host, eff_port = effective_target(host)
    c = FranklinWHController(eff_host, port=eff_port, unit_id=UNIT_ID)
    _no_connect_writes(c)
    try:
        ok = c.connect()
    except Exception as e:                                       # noqa: BLE001
        _record(host, "unreachable", "connect", str(e))
        raise
    if not ok:
        _record(host, "unreachable", "connect", "connect failed")
        raise ConnectionError(f"could not connect to aGate Modbus at {eff_host}:{eff_port}")
    return c, BatteryCommand


#: The four states a dispatch path can be in. They are distinguished because the remedy
#: differs in each case, and a single "unavailable" sends people to the wrong one.
#:
#:   not_configured — nothing to reach (no host), or the client is switched off here
#:   unreachable    — the socket did not open. Firewall, wrong host, gateway down
#:   no_sunspec     — the socket opened but SunSpec did not answer. Almost always the
#:                    gateway's own SunSpec Modbus setting (1205 sunsMdEn) being off
#:   ready          — a SunSpec read SUCCEEDED. Only this state may dispatch
#:
#: A socket that opens is NOT a dispatch path. :502 answering proves a listener exists,
#: nothing more — the same mistake as probing a secured REST API with an unauthenticated
#: health endpoint and calling it available (#56).
STATES = ("not_configured", "unreachable", "no_sunspec", "ready")

CAPABILITY_HINTS = {
    "not_configured": "Set the gateway host, and switch the Modbus client on in Control "
                      "settings.",
    "unreachable": "Nothing answered on TCP 502. Check the address, the gateway, and "
                   "anything filtering the port.",
    "no_sunspec": "The port answered but SunSpec did not. Turn on SunSpec Modbus on the "
                  "gateway — the Device tab's der_comms (1205) read shows sunsMdEn.",
    "ready": "",
}


def capability(host: str | None) -> dict:
    """``{"state", "reason", "hint", "ready"}`` — confirmed, not assumed.

    Confirmation is a SunSpec read that returns, because that is the only evidence that a
    dispatch would land. Nothing here writes.
    """
    def _out(state, reason=""):
        return {"state": state, "reason": reason, "hint": CAPABILITY_HINTS.get(state, ""),
                "ready": state == "ready"}

    if not host:
        return _out("not_configured", "no gateway host to reach over Modbus")
    ok, why = available()
    if not ok:
        return _out("not_configured", why)
    if is_mock_target(host):
        return _out("not_configured", MOCK_REASON)
    try:
        c, _ = _connect(host)
    except Exception as e:                                       # noqa: BLE001
        return _out("unreachable", str(e))
    try:
        c.read_control_status()                  # a real SunSpec read — the confirmation
    except Exception as e:                                       # noqa: BLE001
        _record(host, "no_sunspec", "capability", f"{type(e).__name__}: {e}")
        return _out("no_sunspec", f"{type(e).__name__}: {e}")
    finally:
        _close(c)
    _record(host, "ready", "capability")
    return _out("ready")


def status(host: str) -> dict:
    """Read-only probe: is the WSet path reachable, and what is running now."""
    ok, why = available()
    if not ok:
        return {"available": False, "reason": why,
                "state": "not_configured", "hint": CAPABILITY_HINTS["not_configured"]}
    if is_mock_target(host):
        return {"available": False, "reason": MOCK_REASON,
                "state": "not_configured", "hint": CAPABILITY_HINTS["not_configured"]}
    try:
        c, _ = _connect(host)
    except Exception as e:                                       # noqa: BLE001
        return {"available": False, "reason": str(e),
                "state": "unreachable", "hint": CAPABILITY_HINTS["unreachable"]}
    try:
        cs = c.read_control_status()
        active = "Not Active"
        if cs.get("wset_enabled"):
            # franklinwh-modbus 0.10.1 writes the force as watts (WSetMod=1 + WSet) and no
            # longer sets WSetPct, which then reads 0 and made a running discharge show as
            # "Force Standby". Read the field the active mode uses; same sign either way
            # (negative = charge).
            val = (cs.get("wset_watts") if cs.get("wset_mode") == 1 else cs.get("wset_pct")) or 0
            active = ("Force Charge" if val < 0
                      else "Force Discharge" if val > 0 else "Force Standby")
        rated = _ratings(c)
        _record(host, "ready", "status")
        return {"available": True, "reason": "", "active": active,
                "state": "ready", "hint": "",
                "vpp_active": bool(cs.get("wset_enabled")),
                "max_charge_w": rated[0], "max_discharge_w": rated[1], "wset": cs}
    except Exception as e:                                       # noqa: BLE001
        # The socket opened and SunSpec did not answer: a different problem, and a
        # different remedy, from "could not connect".
        _record(host, "no_sunspec", "status", f"{type(e).__name__}: {e}")
        return {"available": False, "reason": f"{type(e).__name__}: {e}",
                "state": "no_sunspec", "hint": CAPABILITY_HINTS["no_sunspec"]}
    finally:
        _close(c)


def _ratings(c) -> tuple[int, int]:
    """The charge/discharge ratings the LIBRARY will clamp against (#213).

    Always read from the controller's own attributes, even when discovery fails: a
    fallback number of our own that is higher than the library's would pass the bridge's
    clamp and reach the library's, which (0.9.5) inverts the direction."""
    try:
        c.discover_ratings()
    except Exception:                                           # noqa: BLE001
        pass
    return (int(getattr(c, "RATED_MAX_CHARGE_W", 5000) or 5000),
            int(getattr(c, "RATED_MAX_DISCHARGE_W", 5000) or 5000))


#: host -> (expires_at_monotonic, (max_charge_w, max_discharge_w) | (None, None)).
#: Ratings are static hardware specs, so a long TTL is fine; failures are cached too
#: so an unreachable/absent Modbus is attempted at most once per TTL (bounded latency).
_RATINGS_CACHE: dict[str, tuple[float, tuple]] = {}
_RATINGS_TTL = 3600.0


def cached_ratings(host: str) -> tuple:
    """Max charge/discharge W from Modbus SunSpec 702, cached ~1 h. Returns
    ``(max_charge_w, max_discharge_w)`` or ``(None, None)`` when Modbus is not
    available/reachable — the caller then falls back (e.g. to the user constant)."""
    import time as _t
    ok, _why = available()
    if not ok or not host or is_mock_target(host):
        return (None, None)
    now = _t.monotonic()
    hit = _RATINGS_CACHE.get(host)
    if hit and hit[0] > now:
        return hit[1]
    result: tuple = (None, None)
    try:
        c, _ = _connect(host)
        try:
            result = _ratings(c)                # (chg, dis); (5000,5000) if discover fails
        finally:
            _close(c)
    except Exception:                                           # noqa: BLE001
        result = (None, None)                    # unreachable → fall back
    _RATINGS_CACHE[host] = (now + _RATINGS_TTL, result)
    return result


def execute(command: str, *, host: str, power_w: int = 0, power_pct: int = 0,
            power_mode: str = "pct", duration_s: int = 0, target_soc: int = 0,
            soc_getter=None, on_event=None, dry_run: bool = False) -> dict:
    """Run a Battery Command. ``power_mode`` ('pct'|'w') = last-set-wins. A successful
    force arms the bridge's own watchdog which enforces BOTH ``duration_s`` and
    ``target_soc`` (charge stops at SoC>=target, discharge at SoC<=target), using
    ``soc_getter`` for live SoC. ``on_event(status, detail)`` records dispatch
    start/end to the activity log. ``dry_run`` computes without writing.
    """
    global _soc_getter, _on_event
    if soc_getter is not None:
        _soc_getter = soc_getter
    if on_event is not None:
        _on_event = on_event
    cmd = (command or "").strip()
    # The UI disables the controls, but the UI is not the gate — the API is. A force
    # first confirms the path is ready. A release skips that check (refusing to STOP a
    # dispatch because the path looks unhealthy is the wrong way round), but it still
    # needs a connection, so it cannot run with the Modbus client switched off (#174).
    if cmd not in ("Release", "Not Active"):
        cap = capability(host)
        if not cap["ready"]:
            return {"ok": False, "result": cap["reason"] or cap["state"],
                    "state": cap["state"], "hint": cap["hint"]}
    else:
        ok, why = available()
        if not ok:
            held = current().get("active")
            if held not in (None, "Not Active"):
                why = (f"{why}. The {held} this bridge started is still active on the aGate: "
                       "switch the Modbus client on in Control → Modbus client, then Release.")
            return {"ok": False, "result": why, "state": "not_configured"}
        if is_mock_target(host):
            return {"ok": False, "result": MOCK_REASON, "state": "not_configured"}
    try:
        c, BatteryCommand = _connect(host)
    except Exception as e:                                       # noqa: BLE001
        return {"ok": False, "result": str(e)}
    try:
        if cmd in ("Release", "Not Active"):
            if dry_run:
                return {"ok": True, "result": "[dry-run] release", "active": "Not Active"}
            was = current().get("active")
            c.reset_control_state()
            # Report what the aGate says, not what was sent (#174).
            try:
                still = bool(c.read_control_status().get("wset_enabled"))
            except Exception as e:                               # noqa: BLE001
                _clear_active()
                if was not in (None, "Not Active"):
                    _fire("dispatch-end", "released — manual (Release), not confirmed")
                return {"ok": True, "confirmed": False, "active": "Not Active",
                        "result": f"release sent; not confirmed (read-back failed: "
                                  f"{type(e).__name__})"}
            _record(host, "ready", "release")
            if still:
                log.warning("battery release: the aGate still reports the force enabled")
                return {"ok": False, "confirmed": True, "active": was or "Not Active",
                        "result": "release sent, but the aGate still reports a force "
                                  "enabled (WSetEna on)"}
            _clear_active()
            if was not in (None, "Not Active"):
                _fire("dispatch-end", "released — manual (Release)")
            return {"ok": True, "confirmed": True, "result": "released",
                    "active": "Not Active"}

        max_ch, max_dis = _ratings(c)
        clamp_note = ""
        # Last-set-wins: use watts OR percent of the rated rate for the direction.
        if cmd == "Force Standby":
            watts = 0
        elif cmd in ("Force Charge", "Force Discharge"):
            limit = max_ch if cmd == "Force Charge" else max_dis
            if power_mode == "w":
                base = abs(int(power_w or 0))
            else:
                base = int(limit * min(max(int(power_pct or 0), 0), 100) / 100)
            # Never hand the library more than the rating (#213). franklinwh-modbus 0.9.5's
            # own clamp returns the limit with the OPPOSITE sign, so an over-rating Force
            # Charge was sent as a full-rate DISCHARGE (and vice versa). Clamp here, keeping
            # the direction, and say so.
            if base > limit:
                clamp_note = f" (requested {base}W, limited to the {limit}W rating)"
                log.warning("battery %s: %sW exceeds the %sW rating — limited to %sW",
                            cmd, base, limit, limit)
                base = limit
            watts = base if cmd == "Force Charge" else -base
        else:
            return {"ok": False, "result": f"unknown command '{cmd}'"}

        # We own the timer via _arm_watchdog, so don't hand the library a duration
        # whose thread would die with this request.
        okc, msg = c.send_command(BatteryCommand(power_watts=watts), dry_run=dry_run)
        if okc:
            _record(host, "ready", "force")
        if okc and not dry_run:
            _arm_watchdog(host, cmd, watts, duration_s, target_soc)
            _fire("dispatch-start",
                  f"{cmd} — {abs(watts)}W ({'charge' if watts > 0 else 'discharge' if watts < 0 else 'hold'}), "
                  f"power_mode={power_mode}, duration={duration_s or 'none'}s, "
                  f"target_soc={str(target_soc) + '%' if target_soc else 'off'}")
        active = None if dry_run else (cmd if okc else "Not Active")
        return {"ok": bool(okc), "result": (("[dry-run] " + msg) if dry_run else msg) + clamp_note,
                "active": active, "watts": watts}
    except Exception as e:                                       # noqa: BLE001
        return {"ok": False, "result": f"{type(e).__name__}: {e}"}
    finally:
        _close(c)


def _close(c) -> None:
    try:
        c.disconnect()
    except Exception:                                           # noqa: BLE001
        pass
