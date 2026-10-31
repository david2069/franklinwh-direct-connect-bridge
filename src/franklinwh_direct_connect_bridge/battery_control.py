"""Direct-Modbus battery force control.

Reuses the proven ``franklinwh-modbus`` library (``FranklinWHController`` + WSet
Model 704) to drive the aGate's power setpoint directly over Modbus TCP —
independent of the modbus-bridge SERVICE. Force writes MOVE the battery. The
hardware WSetRvrtTms is cosmetic on this firmware and the library is given no
duration, so this module's own watchdog is the only safety; always release when done.
"""
from __future__ import annotations

import logging
import threading
import time

log = logging.getLogger(__name__)

MODBUS_PORT = 502
UNIT_ID = 2  # FranklinWH default (per the library)

# In-memory record of the forces WE started, one per aGate (#194), keyed by host part, so
# the bridge owns each one's watchdog and Release, independent of any per-request Modbus
# connection. Each record carries its own stop event, SoC reader and event sink, so a
# force on a second gateway never ends or rewires the first one's.
_active: dict[str, dict] = {}  # host part -> {command, watts, host, started, duration_s,
                               #   target_soc, key, stop, soc_getter, on_event}
_lock = threading.Lock()


def _view(rec: dict) -> dict:
    rem = None
    if rec.get("duration_s"):
        rem = max(0, int(rec["duration_s"] - (time.time() - rec["started"])))
    return {"active": rec["command"], "watts": rec.get("watts"),
            "duration_s": rec.get("duration_s"), "target_soc": rec.get("target_soc"),
            "remaining_s": rem, "host": rec.get("host")}


def current(host: str | None = None) -> dict:
    """The force this bridge is holding on ``host`` (fast; no Modbus). Empty = Not Active.
    Without a host: the most recent force on any aGate."""
    with _lock:
        if host:
            rec = _active.get(_host_part(host))
        else:
            rec = max(_active.values(), key=lambda r: r["started"], default=None)
        return _view(rec) if rec else {"active": "Not Active"}


def held_hosts() -> list[str]:
    """Every host this bridge is holding a force on (fast; no Modbus)."""
    with _lock:
        return [r["host"] for r in _active.values()]


def holds_force(*hosts) -> bool:
    """True when this bridge is holding a force on one of ``hosts`` (fast; no Modbus).
    The dashboard shows FORCE only for these; any other remote controller is VPP (#333)."""
    with _lock:
        held = set(_active)
    return bool(held & {_host_part(h) for h in hosts if h})


def _fire(status: str, detail: str, rec: dict | None = None, sink=None) -> None:
    """Record a dispatch event with the force's own sink, else the caller's (#355)."""
    sink = (rec or {}).get("on_event") or sink
    if sink:
        try:
            sink(status, detail)
        except Exception:                                       # noqa: BLE001
            pass


def _release_now(host: str, key: float, reason: str) -> None:
    try:
        c, _ = _connect(host)
        try:
            c.reset_control_state()
        finally:
            _close(c)
    except Exception as e:                                       # noqa: BLE001
        log.error("battery force auto-release FAILED (%s): %s", reason, e)
    with _lock:
        rec = _active.get(_host_part(host))
        if rec and rec["key"] == key:
            del _active[_host_part(host)]
    log.warning("battery force: released on %s (%s)", _host_part(host), reason)
    _fire("dispatch-end", f"released — {reason}", rec)


def _watchdog_loop(host: str, key: float, duration_s: int, target_soc: int, watts) -> None:
    """Enforce Duration AND Target SoC (charge stops at SoC>=target, discharge at
    SoC<=target). SoC comes from the poller's cache via the force's own SoC reader — no
    extra Modbus read. Ends the moment a newer command on the same aGate supersedes it.

    Beats the ``dispatch-watchdog`` worker while a force is active and parks it as
    PAUSED when the last one ends, so an idle watchdog is never reported as failed (#93)."""
    try:
        _beat(running=True)
        _watch(host, key, duration_s, target_soc, watts)
    finally:
        with _lock:
            idle = not _active
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
    hp = _host_part(host)
    with _lock:
        rec = _active.get(hp)
        if not rec or rec["key"] != key:
            return
        stop, soc_getter = rec["stop"], rec.get("soc_getter")
    while not stop.wait(5.0):
        _beat(running=True)
        with _lock:
            rec = _active.get(hp)
            if not rec or rec["key"] != key:
                return
            started = rec["started"]
        if duration_s and (time.time() - started) >= duration_s:
            _release_now(host, key, f"duration {duration_s}s reached"); return
        if target_soc and soc_getter:
            try:
                soc = soc_getter()
            except Exception:                                   # noqa: BLE001
                soc = None
            if soc is not None:
                if watts > 0 and soc >= target_soc:
                    _release_now(host, key, f"target reached (SoC {soc}% ≥ {target_soc}%)")
                    return
                if watts < 0 and soc <= target_soc:
                    _release_now(host, key, f"target reached (SoC {soc}% ≤ {target_soc}%)")
                    return


def _arm_watchdog(host: str, command: str, watts, duration_s: int, target_soc: int, *,
                  soc_getter=None, on_event=None) -> None:
    """Hold a force on ``host``: replaces only that aGate's earlier force, if any. The SoC
    reader and event sink are this call's own, never shared state, so two gateways'
    forces armed at the same moment can't swap them (#355)."""
    hp = _host_part(host)
    with _lock:
        key = time.monotonic()
        old = _active.get(hp)
        _active[hp] = {"command": command, "watts": watts, "host": host,
                       "started": time.time(), "duration_s": int(duration_s or 0),
                       "target_soc": int(target_soc or 0), "key": key,
                       "stop": threading.Event(), "soc_getter": soc_getter,
                       "on_event": on_event}
    if old:
        old["stop"].set()             # end that aGate's prior loop; others keep running
    t = threading.Thread(target=_watchdog_loop,
                         args=(host, key, int(duration_s or 0), int(target_soc or 0), watts),
                         daemon=True)
    t.start()


def _clear_active(host: str | None = None) -> None:
    """Forget the force on ``host``, or every force when no host is given."""
    with _lock:
        recs = ([_active.pop(_host_part(host))] if host and _host_part(host) in _active
                else [] if host else list(_active.values()))
        if not host:
            _active.clear()
    for r in recs:
        r["stop"].set()


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
                _arm_watchdog(host, current(host).get("active") or cmd, watts, remaining, tgt,
                              soc_getter=soc_getter, on_event=on_event)
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


def release_held(reason: str) -> None:
    """Release every force this bridge holds, each on its own aGate (#192)."""
    for host in held_hosts():
        log.warning("battery force: releasing %s on %s (%s)",
                    current(host).get("active"), host, reason)
        execute("Release", host=host)


def _gateway_soc(host: str):
    """A SoC reader for the gateway on ``host``, from its poller's cache (no Modbus)."""
    def _soc():
        try:
            from . import state
            hp = _host_part(host)
            for gw in state.gateways():
                if hp in {_host_part(h) for h in (gw.active_host, gw.configured_host) if h}:
                    return (getattr(gw, "last_state", {}) or {}).get("soc")
        except Exception:                                       # noqa: BLE001
            pass
        return None
    return _soc


def reconcile_all(store, policy: str, *, notify=None) -> list[dict]:
    """Boot reconcile on every aGate with an open dispatch row (#192), each with its own
    gateway's SoC reader. Never raises."""
    try:
        hosts = sorted({d.get("host") for d in store.active_dispatches() if d.get("host")})
    except Exception as e:                                       # noqa: BLE001
        return [{"action": "error", "detail": str(e)}]
    out: list[dict] = []
    for h in hosts:
        out += reconcile_interrupted(store, h, policy, soc_getter=_gateway_soc(h),
                                     notify=notify)
    return out


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


def _is_default_host(host: str | None) -> bool:
    """True when ``host`` is the default gateway's, or there is only one gateway."""
    from . import state
    gws = state.gateways()
    default = state.default_gateway()
    if len(gws) <= 1 or not host or default is None:
        return True
    mine = {h for h in (default.active_host, default.configured_host) if h}
    if host in mine:
        return True
    others = {_host_part(h) for g in gws if g is not default
              for h in (g.active_host, g.configured_host) if h}
    return _host_part(host) in {_host_part(h) for h in mine} and _host_part(host) not in others


def _override_for(host: str | None) -> tuple | None:
    """The (host, port) to use instead of ``host``: the persisted override. It applies only
    to the DEFAULT gateway; every other gateway keeps its own host, so one setting can't
    send every gateway's force to one aGate (#354). ``FWH_MODBUS_HOST`` is gone (#379):
    every gateway's Modbus client connects to its own host."""
    if not _HOST_OVERRIDE:
        return None
    target = (_HOST_OVERRIDE, _PORT_OVERRIDE or MODBUS_PORT)
    return target if _is_default_host(host) else None


def effective_target(host: str | None) -> tuple:
    """The (host, port) actually used for Modbus: the override for the default gateway when
    one is set, else the passed gateway host split into (host, port) — so a mock's
    ``127.0.0.1:<ephemeral>`` is handled and a bare IP keeps the default 502. This is the
    single source of truth for the target."""
    from .client import _split_hostport
    ov = _override_for(host)
    if ov:
        return ov
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
    pointed the client somewhere real (default gateway only, #354)."""
    if not host or _override_for(host):
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
            held = current(host).get("active")
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
            was = current(host).get("active")
            with _lock:
                held = _active.get(_host_part(host))     # its own event sink, for the end
            c.reset_control_state()
            # Report what the aGate says, not what was sent (#174).
            try:
                still = bool(c.read_control_status().get("wset_enabled"))
            except Exception as e:                               # noqa: BLE001
                _clear_active(host)
                if was not in (None, "Not Active"):
                    _fire("dispatch-end", "released — manual (Release), not confirmed", held,
                          on_event)
                return {"ok": True, "confirmed": False, "active": "Not Active",
                        "result": f"release sent; not confirmed (read-back failed: "
                                  f"{type(e).__name__})"}
            _record(host, "ready", "release")
            if still:
                log.warning("battery release: the aGate still reports the force enabled")
                return {"ok": False, "confirmed": True, "active": was or "Not Active",
                        "result": "release sent, but the aGate still reports a force "
                                  "enabled (WSetEna on)"}
            _clear_active(host)
            if was not in (None, "Not Active"):
                _fire("dispatch-end", "released — manual (Release)", held, on_event)
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
            _arm_watchdog(host, cmd, watts, duration_s, target_soc,
                          soc_getter=soc_getter, on_event=on_event)
            _fire("dispatch-start",
                  f"{cmd} — {abs(watts)}W ({'charge' if watts > 0 else 'discharge' if watts < 0 else 'hold'}), "
                  f"power_mode={power_mode}, duration={duration_s or 'none'}s, "
                  f"target_soc={str(target_soc) + '%' if target_soc else 'off'}",
                  sink=on_event)
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
