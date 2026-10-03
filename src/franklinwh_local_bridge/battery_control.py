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
    Modbus read. Ends the moment a newer command supersedes this one."""
    while not _stop.wait(5.0):
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


#: User master switch for the direct-Modbus (SunSpec 502) path — ratings AND force
#: dispatch. Toggled from the Control tab (persisted as the ``modbus_enabled`` config);
#: applied at startup. Default on. When off, ``available()`` reports disabled and every
#: caller falls back (ratings → user constant; dispatch → 503).
_ENABLED = True


def set_enabled(on: bool) -> None:
    global _ENABLED
    _ENABLED = bool(on)


def is_enabled() -> bool:
    return _ENABLED


def available() -> tuple[bool, str]:
    if not _ENABLED:
        return False, "Modbus (SunSpec 502) is disabled in Control settings"
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


def _connect(host: str):
    FranklinWHController, BatteryCommand = _lib()
    eff_host, eff_port = effective_target(host)
    c = FranklinWHController(eff_host, port=eff_port, unit_id=UNIT_ID)
    if not c.connect():
        raise ConnectionError(f"could not connect to aGate Modbus at {eff_host}:{eff_port}")
    return c, BatteryCommand


def status(host: str) -> dict:
    """Read-only probe: is the WSet path reachable, and what is running now."""
    ok, why = available()
    if not ok:
        return {"available": False, "reason": why}
    try:
        c, _ = _connect(host)
    except Exception as e:                                       # noqa: BLE001
        return {"available": False, "reason": str(e)}
    try:
        cs = c.read_control_status()
        active = "Not Active"
        if cs.get("wset_enabled"):
            pct = cs.get("wset_pct") or 0
            active = ("Force Charge" if pct < 0
                      else "Force Discharge" if pct > 0 else "Force Standby")
        rated = _ratings(c)
        return {"available": True, "reason": "", "active": active,
                "vpp_active": bool(cs.get("wset_enabled")),
                "max_charge_w": rated[0], "max_discharge_w": rated[1], "wset": cs}
    except Exception as e:                                       # noqa: BLE001
        return {"available": False, "reason": f"{type(e).__name__}: {e}"}
    finally:
        _close(c)


def _ratings(c) -> tuple[int, int]:
    try:
        c.discover_ratings()
        return (int(getattr(c, "RATED_MAX_CHARGE_W", 5000) or 5000),
                int(getattr(c, "RATED_MAX_DISCHARGE_W", 5000) or 5000))
    except Exception:                                           # noqa: BLE001
        return (5000, 5000)


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
    if not ok or not host:
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
    ok, why = available()
    if not ok:
        return {"ok": False, "result": why}
    cmd = (command or "").strip()
    try:
        c, BatteryCommand = _connect(host)
    except Exception as e:                                       # noqa: BLE001
        return {"ok": False, "result": str(e)}
    try:
        if cmd in ("Release", "Not Active"):
            if not dry_run:
                was = current().get("active")
                c.reset_control_state()
                _clear_active()
                if was not in (None, "Not Active"):
                    _fire("dispatch-end", "released — manual (Release)")
            return {"ok": True, "result": "released", "active": "Not Active"}

        max_ch, max_dis = _ratings(c)
        # Last-set-wins: use watts OR percent of the rated rate for the direction.
        if cmd == "Force Standby":
            watts = 0
        elif cmd in ("Force Charge", "Force Discharge"):
            if power_mode == "w":
                base = int(power_w or 0)
            else:
                base = int((max_ch if cmd == "Force Charge" else max_dis) * (power_pct or 0) / 100)
            watts = abs(base) if cmd == "Force Charge" else -abs(base)
        else:
            return {"ok": False, "result": f"unknown command '{cmd}'"}

        # We own the timer via _arm_watchdog, so don't hand the library a duration
        # whose thread would die with this request.
        okc, msg = c.send_command(BatteryCommand(power_watts=watts), dry_run=dry_run)
        if okc and not dry_run:
            _arm_watchdog(host, cmd, watts, duration_s, target_soc)
            _fire("dispatch-start",
                  f"{cmd} — {abs(watts)}W ({'charge' if watts > 0 else 'discharge' if watts < 0 else 'hold'}), "
                  f"power_mode={power_mode}, duration={duration_s or 'none'}s, "
                  f"target_soc={str(target_soc) + '%' if target_soc else 'off'}")
        active = None if dry_run else (cmd if okc else "Not Active")
        return {"ok": bool(okc), "result": ("[dry-run] " + msg) if dry_run else msg,
                "active": active}
    except Exception as e:                                       # noqa: BLE001
        return {"ok": False, "result": f"{type(e).__name__}: {e}"}
    finally:
        _close(c)


def _close(c) -> None:
    try:
        c.disconnect()
    except Exception:                                           # noqa: BLE001
        pass
