"""Actionable Home Assistant notifications (#374), through franklinwh-ha-notify.

One :class:`~franklinwh_ha_notify.Notifier` per bridge process. It covers every enabled
Home Assistant instance in the store, records sends and taps in the ``notify_ledger``
table (created by the store's migration), and is off whenever the ``ha_notify`` master
switch is off. Taps arrive over each instance's authenticated WebSocket; nothing on the
bridge accepts an unauthenticated call.

Events and their handlers are registered by the features that use them
(``notifier().templates.register(...)`` and ``notifier().on(...)``), at import time,
before :func:`start` opens the listeners.
"""
from __future__ import annotations

import asyncio
import logging
import sqlite3

from franklinwh_ha_notify import HAInstance, Ledger, Notifier, SendResult, Target, Templates

log = logging.getLogger(__name__)

_notifier: Notifier | None = None
_templates = Templates()


def templates() -> Templates:
    """The shared template registry. Usable before :func:`start`."""
    return _templates


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
    """A Notifier over ``store``'s HA instances and ledger. No listeners started."""
    conn = sqlite3.connect(store.path, check_same_thread=False)
    return Notifier(_instances(store), Ledger(conn, create=False), _templates,
                    enabled=lambda: bool(settings.ha_notify))


def notifier() -> Notifier | None:
    """The running Notifier, or None before :func:`start` (or when it failed)."""
    return _notifier


def gateway_name(gateway_id: str | None) -> str:
    """The gateway's label for a message (#361). No id means the default gateway."""
    from . import state
    gw = state.get_gateway(gateway_id) if gateway_id else state.default_gateway()
    if gw is None:
        return gateway_id or ""
    return gw.label or gw.id


def device_targets(store, device_ids: list[str] | None = None) -> list[Target]:
    """The companion devices to send to: every enabled one, or exactly ``device_ids``.
    A switched-off HA instance suppresses its devices."""
    by_id = {i["id"]: i for i in store.ha_instances()}
    out = []
    for d in store.notify_devices():
        if (d["id"] not in device_ids) if device_ids is not None else not d.get("enabled"):
            continue
        inst = by_id.get(d["instance_id"])
        if inst is not None and not inst.get("enabled", 1):
            continue
        out.append(Target(d["instance_id"], d["service"].removeprefix("notify."),
                          d.get("alias") or d["id"]))
    return out


def send(store, event: str, *, gateway: str | None = None,
         device_ids: list[str] | None = None, **values) -> SendResult | None:
    """Send ``event`` to the companion devices through the one Notifier, from a worker
    thread. The Notifier applies the master switch and records the send in the ledger.
    None when notifications have not started."""
    n = _notifier
    if n is None:
        log.info("notify [%s] not sent: notifications have not started", event)
        return None
    # Instances added or switched since start are picked up here, not at a restart.
    n.instances = _instances(store)
    return asyncio.run(n.notify(event, device_targets(store, device_ids),
                                gateway=gateway, **values))


async def start(store, settings) -> Notifier | None:
    """Build the Notifier and open one tap listener per HA instance. Never raises."""
    global _notifier
    if store is None:
        return None
    try:
        _notifier = build(store, settings)
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
