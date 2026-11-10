"""Buttons on the bridge's notifications (#374 P3): Release, Acknowledge, Re-discover,
and the test round trip.

Each button calls the bridge's own existing command: Release is
``battery_control.execute("Release")``, as the top-bar Release; Acknowledge is
``alerts.ack`` with source ``ha``; Re-discover asks the gateway's poller for its own
re-discovery sweep. The asks ride on the notifications the bridge already sends; the
callers send the plain one only when the ask went nowhere.

Requests survive a restart (franklinwh-ha-notify#6), so a tap can arrive long after the
state it was asked about has changed. Each handler is therefore idempotent: releasing a
force that is no longer running, or acknowledging an alert already acknowledged, does
nothing and says so.
"""
from __future__ import annotations

import asyncio
import logging

from franklinwh_ha_notify import NO, YES, Button, Event

from . import actionable

log = logging.getLogger(__name__)

FORCE_RUNNING = "force_running"
ALERT = "alert"
TEST = "test_buttons"
#: The Test critical alert from Settings (#464): the alert's path, with no alert record.
TEST_ALERT = "test_alert"
#: Its Home Assistant persistent notification.
TEST_ALERT_NID = "fwh_dc_alert_test"

RELEASE, ACK, REDISCOVER = "RELEASE", "ACK", "REDISCOVER"

RELEASE_TTL_S = 900
ALERT_TTL_S = 3600
TEST_TTL_S = 120
TEST_ALERT_TTL_S = 300
#: How long a worker thread waits for the send itself (not for a tap).
SEND_WAIT_S = 30

actionable.templates().register(
    Event(FORCE_RUNNING, "{title}", "{message}", ("title", "message"),
          "A battery force is still running: Release or Keep."),
    Event(ALERT, "{title}", "{message}", ("title", "message"),
          "A bridge alert: Acknowledge (and Re-discover when the aGate is unreachable)."),
    Event(TEST, "FranklinWH test", "Tap Yes or No to check buttons reach the bridge.", (),
          "The test with buttons from Settings."),
    Event(TEST_ALERT, "{title}", "{message}", ("title", "message"),
          "The Test critical alert from Settings: Acknowledge, as a real alert."),
)


def _store():
    from . import db
    from .config import get_settings
    return db.get_store(get_settings())


def _label_for_host(host: str) -> str | None:
    from . import battery_control, state
    hp = battery_control._host_part(host)
    for gw in state.gateways():
        if hp in {battery_control._host_part(h) for h in (gw.active_host, gw.configured_host) if h}:
            return gw.label or gw.id
    return None


def _ask_from_thread(store, event: str, buttons: list[Button], ttl_s: float, *,
                     gateway: str | None, meta: dict, **values) -> bool:
    """Send an ask from a worker thread; True when it reached at least one target."""
    from . import notify_engine
    n = actionable.notifier()
    if n is None:
        return False
    # Its Send to setting (#281): all enabled devices, or the ones chosen.
    ids = notify_engine.send_to_ids(store, event)
    fut = actionable.submit(n.ask(event, actionable.targets(store, ids), buttons, ttl_s=ttl_s,
                                  gateway=gateway, meta=meta, **values))
    if fut is None:
        return False
    try:
        return fut.result(timeout=SEND_WAIT_S) is not None
    except Exception as e:  # noqa: BLE001 - the caller falls back to its plain send
        log.warning("notification with buttons not sent (%s): %s", event, e)
        return False


# ── Release / Keep ───────────────────────────────────────────────────────────────
#: What a Release / Keep question is about: a force seen over Modbus (the M704 WSet bit),
#: or a VPP seen on the local channel (1707 programme id 9, the VPP-at-boot ask), which
#: may be a remote controller that is not a WSet force.
FORCE, VPP = "force", "vpp"


def ask_release(store, host: str, title: str, message: str, *, about: str = FORCE) -> bool:
    """Ask Release / Keep about a force (or, ``about=VPP``, a VPP) running on ``host``.
    The question keeps which force this bridge held then, so a tap never releases a later
    one."""
    from . import battery_control
    return _ask_from_thread(store, FORCE_RUNNING, [Button(RELEASE, "Release"), Button(NO, "Keep")],
                            RELEASE_TTL_S, gateway=_label_for_host(host),
                            meta={"host": host, "about": about,
                                  "force": battery_control.force_id(host)},
                            title=title, message=message)


def _vpp_now(host: str) -> bool | None:
    """The gateway's VPP state from its last local reading (1707), None when unknown."""
    from . import battery_control, state
    hp = battery_control._host_part(host)
    for gw in state.gateways():
        if hp in {battery_control._host_part(h) for h in (gw.active_host, gw.configured_host) if h}:
            return gw.vpp_active
    return None


async def _on_release(request, answer) -> str:
    if answer.verb != RELEASE:
        return "kept"
    from . import battery_control
    host = request.meta["host"]
    # Not the force asked about: this bridge has started (or ended) one since.
    held = battery_control.force_id(host)
    if request.meta.get("force") != held:
        if held is not None:
            log.info("Release tapped for %s: a different force is running; left alone", host)
            return "not released: a different force is running"
        log.info("Release tapped for %s: the force asked about has ended; nothing to do", host)
        return "already released"
    vpp = _vpp_now(host) if request.meta.get("about") == VPP else None
    if vpp is False:
        log.info("Release tapped for %s: the VPP has ended; nothing to do", host)
        return "already released"
    now = await asyncio.to_thread(battery_control.status, host)
    if now.get("available") and not now.get("vpp_active"):
        if vpp:
            log.info("Release tapped for %s: the VPP is not a Modbus (WSet) force; "
                     "left alone", host)
            return "not released: the VPP is not a Modbus force this bridge can release"
        log.info("Release tapped for %s: no force is running there; nothing to do", host)
        return "already released"
    out = await asyncio.to_thread(battery_control.execute, "Release", host=host)
    if not out.get("ok"):
        return f"not released: {out.get('result', '')}"
    st = _store()
    if st is not None:      # as the top-bar Release: close the open dispatch rows
        await asyncio.to_thread(st.end_active_dispatches, host=host, status="ended")
    return "released"


# ── Acknowledge / Re-discover ────────────────────────────────────────────────────
def ask_alert(store, row: dict) -> bool:
    """Ask Acknowledge (plus Re-discover for an unreachable aGate) about one alert."""
    from . import state
    gid = row.get("gateway_id") or ""
    gw = state.get_gateway(gid) if gid else None
    buttons = [Button(ACK, "Acknowledge")]
    if row.get("code") == "GATEWAY_UNREACHABLE" and gw is not None:
        buttons.append(Button(REDISCOVER, "Re-discover"))
    return _ask_from_thread(store, ALERT, buttons, ALERT_TTL_S,
                            gateway=(gw.label or gw.id) if gw else None,
                            meta={"alert_id": row["id"], "gateway_id": gid},
                            title=row.get("title") or "", message=row.get("message") or "")


async def _on_alert(request, answer) -> str:
    if answer.verb == REDISCOVER:
        from . import state
        gw = state.get_gateway(request.meta["gateway_id"])
        if gw is None:
            return "gateway not found"
        gw.rediscover_requested = True
        return "re-discovery requested"
    from . import alerts
    st = _store()
    aid = request.meta["alert_id"]
    before = await asyncio.to_thread(st.alert, aid)
    if before is not None and before.get("acked_ts") is not None:
        log.info("Acknowledge tapped for alert #%s: already acknowledged by %s; nothing to do",
                 aid, before.get("acked_by"))
        return "already acknowledged"
    row = await asyncio.to_thread(alerts.ack, st, aid, "ha")
    return "acknowledged" if row else "alert not found"


# ── test round trip ──────────────────────────────────────────────────────────────
async def _on_test(request, answer) -> str:
    said = "Yes" if answer.verb == YES else "No"
    from . import notify_checks          # the last result, for the Notifications check (#464)
    await asyncio.to_thread(notify_checks.test_tapped, _store(), request.id, said)
    return said


async def _on_test_alert(request, answer) -> str:
    """Acknowledge on the test alert: dismiss its Home Assistant notification, as a real
    acknowledgement does. There is no alert record to acknowledge."""
    from .config import get_settings
    from .notify import Notifier
    err = await asyncio.to_thread(Notifier(get_settings()).call_service,
                                  "persistent_notification", "dismiss",
                                  {"notification_id": TEST_ALERT_NID})
    return "acknowledged" if not err else f"acknowledged (dismiss: {err})"


def yes_no() -> list[Button]:
    return [Button(YES, "Yes"), Button(NO, "No")]


actionable.on(FORCE_RUNNING, _on_release)
actionable.on(ALERT, _on_alert)
actionable.on(TEST, _on_test)
actionable.on(TEST_ALERT, _on_test_alert)
