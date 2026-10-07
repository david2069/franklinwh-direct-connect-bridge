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

log = logging.getLogger(__name__)

# Last observed VPP state, so we only fire on transitions (None = not yet observed).
_last: dict = {"vpp": None}


def reset() -> None:
    _last["vpp"] = None


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


def check(host: str, store, *, boot: bool = False, notify: bool = True) -> dict:
    """One monitor pass. Returns {vpp, changed, event}. Never raises."""
    from . import battery_control
    from . import notify_engine   # dispatch notifications flow through the trigger engine
    try:
        st = battery_control.status(host)
    except Exception as e:                                       # noqa: BLE001
        return {"vpp": None, "changed": False, "error": str(e)}
    if not st.get("available"):
        return {"vpp": None, "changed": False, "reason": st.get("reason")}

    vpp = bool(st.get("vpp_active"))
    ours = battery_control.current().get("active") not in (None, "Not Active")
    w = st.get("wset", {}) or {}
    pct = w.get("wset_pct")
    prev = _last["vpp"]
    _last["vpp"] = vpp

    # VPP active at startup, not started by us. This is NORMAL when enrolled in a VPP
    # (the utility programme, the app, or the Modbus bridge dispatches on its own); it is
    # only an "orphan" if a prior run of THIS bridge left it — which we cannot distinguish
    # here (our in-memory 'current' is cleared on restart). So: WARNING, not CRITICAL.
    if boot and vpp and not ours:
        msg = (f"VPP (force) dispatch active at startup (WSetPct={pct}%) — started externally "
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
        msg = f"Battery dispatch STARTED — VPP mode active (source: {src}, WSetPct={pct}%)."
        log.warning(msg)
        _log_event(store, "vpp-start", msg)
        # Only alert for dispatches WE did not start (ours already show in the widget/log).
        if notify and not ours:
            notify_engine.fire(store, "dispatch", "FranklinWH — battery dispatch started (VPP)", msg)
        return {"vpp": vpp, "changed": True, "event": "start"}

    if prev and not vpp:
        msg = "Battery dispatch ENDED — VPP mode cleared, battery back to normal."
        log.info(msg)
        _log_event(store, "vpp-stop", msg)
        return {"vpp": vpp, "changed": True, "event": "stop"}

    return {"vpp": vpp, "changed": False}
