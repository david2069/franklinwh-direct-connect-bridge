"""Actionable Home Assistant notifications (#374), through franklinwh-ha-notify.

One :class:`~franklinwh_ha_notify.Notifier` per bridge process. It covers every enabled
Home Assistant instance in the store, records sends and taps in the ``notify_ledger``
table and keeps open requests in ``notify_requests`` (both created by the store's
migration), and is off whenever the ``ha_notify`` master
switch is off. Taps arrive over each instance's authenticated WebSocket; nothing on the
bridge accepts an unauthenticated call.

Events and their handlers are registered by the features that use them
(``templates().register(...)`` and :func:`on`), at import time, before :func:`start`
opens the listeners.

The Notifier lives on the app's event loop. A worker thread reaches it with
:func:`submit`.
"""
from __future__ import annotations

import asyncio
import logging
import sqlite3

from franklinwh_ha_notify import (HAInstance, Ledger, Notifier, Requests, SendResult, Target,
                                  Templates)

log = logging.getLogger(__name__)

_notifier: Notifier | None = None
_loop: asyncio.AbstractEventLoop | None = None
_templates = Templates()
_handlers: dict = {}

#: How long a worker thread waits for a send on the Notifier's loop.
SEND_TIMEOUT_S = 30.0


def templates() -> Templates:
    """The shared template registry. Usable before :func:`start`."""
    return _templates


def on(event: str, handler) -> None:
    """Register the handler for taps on ``event``'s buttons; applied by :func:`build`."""
    _handlers[event] = handler


def submit(coro):
    """Run ``coro`` on the Notifier's event loop from a worker thread. Returns a
    ``concurrent.futures.Future``, or None (and the coroutine is closed) when the
    Notifier is not running."""
    if _notifier is None or _loop is None or _loop.is_closed():
        coro.close()
        return None
    return asyncio.run_coroutine_threadsafe(coro, _loop)


def targets(store, device_ids: list[str] | None = None) -> list[Target]:
    """The enabled notify devices in the store, on enabled HA instances, as targets; or,
    with ``device_ids``, exactly those devices (on or off) on enabled instances."""
    live = {r["id"] for r in store.ha_instances() if r.get("enabled", 1)}
    return [Target(d["instance_id"], d["service"].removeprefix("notify."),
                   d.get("alias") or d["service"])
            for d in store.notify_devices()
            if ((d["id"] in device_ids) if device_ids is not None else d.get("enabled"))
            and d["instance_id"] in live]


def gateway_name(gateway_id: str | None) -> str:
    """The gateway's label for a message (#361). No id means the default gateway."""
    from . import state
    gw = state.get_gateway(gateway_id) if gateway_id else state.default_gateway()
    if gw is None:
        return gateway_id or ""
    return gw.label or gw.id


def send(store, event: str, *, gateway: str | None = None,
         device_ids: list[str] | None = None, **values) -> SendResult | None:
    """Send ``event`` (no buttons) to :func:`targets` through the one Notifier, from a
    worker thread, and wait for the result. The Notifier applies the master switch and
    records the send. None when the Notifier is not running."""
    n = _notifier
    if n is None:
        log.info("notify [%s] not sent: notifications are not running", event)
        return None
    fut = submit(n.notify(event, targets(store, device_ids), gateway=gateway, **values))
    if fut is None:
        log.info("notify [%s] not sent: notifications are not running", event)
        return None
    return fut.result(timeout=SEND_TIMEOUT_S)


def sync_instances(store) -> None:
    """Tell the running Notifier that the store's HA instances changed, from a worker
    thread: an added or re-enabled instance gets its tap listener, a changed URL or token
    signs in again, and a disabled or deleted one stops listening. No restart needed
    (franklinwh-ha-notify#5). Does nothing when the Notifier is not running; never raises."""
    n = _notifier
    if n is None or store is None:
        return
    fut = submit(n.set_instances(_instances(store)))
    if fut is None:
        return
    try:
        fut.result(timeout=SEND_TIMEOUT_S)
    except Exception as e:  # noqa: BLE001 - the store change itself already succeeded
        log.warning("HA instances changed, but the tap listeners could not follow: %s", e)


def _instances(store) -> dict[str, HAInstance]:
    out = {}
    for row in store.ha_instances() if store else []:
        if not row.get("enabled", 1) or not row.get("base_url"):
            continue
        hid = row["id"]
        # The token is read on every call: the Supervisor issues a new one per
        # container and the store row is refreshed on start (#99).
        out[hid] = HAInstance(hid, row["base_url"],
                              token=lambda hid=hid: (store.ha_instance(hid) or {}).get("token") or "",
                              name=row.get("name") or "")
    return out


def build(store, settings) -> Notifier:
    """A Notifier over ``store``'s HA instances and ledger, with the registered
    handlers. No listeners started.

    Its requests are kept in the bridge database (``notify_requests``, created by the
    store's migration) as well as in memory, so a tap inside a request's TTL after a
    restart still resolves and runs its handler (franklinwh-ha-notify#6)."""
    conn = sqlite3.connect(store.path, check_same_thread=False)
    n = Notifier(_instances(store), Ledger(conn, create=False), _templates,
                 enabled=lambda: bool(settings.ha_notify),
                 requests=Requests.persistent(conn, create=False))
    for event, handler in _handlers.items():
        n.on(event, handler)
    return n


def notifier() -> Notifier | None:
    """The running Notifier, or None before :func:`start` (or when it failed)."""
    return _notifier


async def start(store, settings) -> Notifier | None:
    """Build the Notifier and open one tap listener per HA instance. Never raises."""
    global _notifier, _loop
    if store is None:
        return None
    try:
        _notifier = build(store, settings)
        _loop = asyncio.get_running_loop()
        _notifier.listen()
        log.info("actionable notifications: listening on %d Home Assistant instance(s)",
                 len(_notifier.instances))
    except Exception as e:  # noqa: BLE001 - notifications must never stop the bridge
        log.error("actionable notifications could not start: %s", e)
        _notifier = None
    return _notifier


async def stop() -> None:
    global _notifier
    if _notifier is not None:
        await _notifier.close()
        _notifier = None
