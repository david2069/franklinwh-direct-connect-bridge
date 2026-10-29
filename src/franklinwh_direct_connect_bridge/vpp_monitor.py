"""VPP dispatch monitor.

Watches the aGate's WSet/VPP (force) state over Modbus and:
  - logs when a battery dispatch STARTS and STOPS (from ANY source — this bridge,
    the Modbus bridge, the official app / cloud VPP),
  - on startup, if VPP is already active and this bridge did not start it, raises a
    WARNING "VPP-at-boot" event (a dispatch active at startup that this bridge did not start —
    because the aGate's hardware revert timer is cosmetic),
  - notifies the user's ENABLED HA notify devices (so they choose the targets), and
    records each event in the schedule activity log.

It never releases anything itself — detection + alert only — so it is safe to run
alongside another controller (respects the two-masters rule). The user acts via the
top-nav Release button.
"""
from __future__ import annotations

import logging
import time

log = logging.getLogger(__name__)

# Last observed VPP state PER aGate host, so we only fire on transitions (None = not yet
# observed), and when its current dispatch was first seen, for its duration. One shared
# state would report one gateway's change against another's (#379).
_last: dict[str, dict] = {}


def reset() -> None:
    _last.clear()


def _metrics(snap: dict) -> str:
    """What the site was doing at the transition, from the poller's snapshot (#300).
    A value the poll did not carry is left out, not shown as 0."""
    parts = [f"{label} {snap[k]:.0f} W" for k, label in (
        ("battery_w", "battery"), ("grid_w", "grid"), ("solar_w", "solar"), ("load_w", "load"))
        if isinstance(snap.get(k), (int, float))]
    if isinstance(snap.get("soc"), (int, float)):
        parts.append(f"SoC {snap['soc']:.1f}%")
    return ", ".join(parts) or "no power reading"


def _notify_devices(store, title: str, message: str) -> int:
    """Send to every ENABLED notify device — the user's chosen targets."""
    from . import ha_instances
    sent = 0
    try:
        by_id = {i["id"]: i for i in store.ha_instances()}
        for d in store.notify_devices():
            if not d.get("enabled"):
                continue
            inst = by_id.get(d["instance_id"])
            if not inst:
                continue
            r = ha_instances.send_notification(inst["base_url"], inst.get("token"),
                                               d["service"], title, message)
            if r.get("ok"):
                sent += 1
    except Exception as e:                                       # noqa: BLE001
        log.error("VPP notify failed: %s", e)
    return sent


def _log_event(store, status: str, detail: str) -> None:
    try:
        store.log_schedule_event("_vpp", "Battery dispatch (VPP)", status, detail)
    except Exception:                                           # noqa: BLE001
        pass


def check(host: str, store, *, boot: bool = False, notify: bool = True,
          snapshot: dict | None = None, label: str | None = None) -> dict:
    """One monitor pass. Returns {vpp, changed, event}. Never raises.

    Reads VPP from the LOCAL channel, not Modbus. `snapshot` is the poller's cached
    power block, which already carries `vpp` and `programme_id` from cmdType 1707 —
    the local equivalent of the cloud's `tou_mode`, where 9 means VPP.

    This used to open a Modbus connection per pass to read the M704 WSet bit. That was
    unnecessary: the vendor reference states that ANY remote client taking direct
    control puts the gateway in VPP Mode, and the aGate reports that on the local
    channel. Measured 2026-10-12 — during a Modbus force, 1707 `ibgRunStatus` read 9
    while 1301 `run_status` stayed 2. See docs/RUN_STATUS_AND_MODE.md.
    """
    from . import battery_control
    from . import notify_engine   # dispatch notifications flow through the trigger engine
    snap = snapshot or {}
    if snap.get("vpp") is None:
        # No local reading yet (first poll, or the gateway did not answer). Report
        # "unknown" rather than "not dispatching" — absence of data is not evidence
        # that the battery is idle.
        return {"vpp": None, "changed": False, "reason": "no local programme reading yet"}

    vpp = bool(snap.get("vpp"))
    ours = battery_control.current(host).get("active") not in (None, "Not Active")
    last = _last.setdefault(host, {"vpp": None, "since": None})
    who = f"{label}: " if label else ""     # which gateway, in every message
    # Actual battery power, which is what is HAPPENING — better than the commanded
    # WSet percentage this used to report, which was only what was asked for.
    prev = last["vpp"]
    last["vpp"] = vpp
    now = time.time()
    if vpp and prev is False:          # a start we saw; one already running has no known start
        last["since"] = now

    # VPP active at startup, not started by us. This is NORMAL when enrolled in a VPP
    # (the utility programme, the app, or the Modbus bridge dispatches on its own); it is
    # only an "orphan" if a prior run of THIS bridge left it — which we cannot distinguish
    # here (our in-memory 'current' is cleared on restart). So: WARNING, not CRITICAL.
    if boot and vpp and not ours:
        msg = (f"{who}VPP (force) dispatch active at startup ({_metrics(snap)}) — started externally "
               f"(a utility VPP programme, the app, the Modbus bridge, or a prior run), not by "
               f"this bridge. This bridge will not auto-release it; use the Release button to "
               f"override if you want to clear it.")
        log.warning(msg)
        _log_event(store, "vpp-at-boot", msg)
        if notify:
            notify_engine.fire(store, "dispatch", "FranklinWH — VPP dispatch active at startup", msg)
        return {"vpp": vpp, "changed": True, "event": "vpp-at-boot"}

    if prev is None:
        return {"vpp": vpp, "changed": False, "event": "observed"}

    if vpp and not prev:
        src = "this bridge" if ours else "an external controller (Modbus bridge / app / cloud VPP)"
        msg = f"{who}Battery dispatch STARTED — VPP mode active (source: {src}; {_metrics(snap)})."
        log.warning(msg)
        _log_event(store, "vpp-start", msg)
        # Only alert for dispatches WE did not start (ours already show in the widget/log).
        if notify and not ours:
            notify_engine.fire(store, "dispatch", "FranklinWH — battery dispatch started (VPP)", msg)
        return {"vpp": vpp, "changed": True, "event": "start"}

    if prev and not vpp:
        since, last["since"] = last["since"], None
        took = f" after {now - since:.0f} s" if since else ""
        msg = (f"{who}Battery dispatch ENDED{took} — VPP mode cleared, battery back to normal "
               f"({_metrics(snap)}).")
        log.info(msg)
        _log_event(store, "vpp-stop", msg)
        return {"vpp": vpp, "changed": True, "event": "stop"}

    return {"vpp": vpp, "changed": False}
