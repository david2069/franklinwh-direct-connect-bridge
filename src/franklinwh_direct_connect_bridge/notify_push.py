"""The one path for companion pushes (``notify.*``), through franklinwh-ha-notify (#374 P2).

There used to be four: the trigger engine, the scheduler's notify action, the VPP
monitor, and the device test/broadcast endpoints. Each called
``ha_instances.send_notification`` itself, none checked the Push notifications switch
(#171), and only the trigger engine wrote the notification log. Now every one of them
calls :func:`push`, which checks the switch, sends through the shared package, and logs
each device's delivery.

Callers are synchronous and run in worker threads (the poller and scheduler use
``to_thread``; FastAPI runs sync endpoints in its thread pool), so the package's async
send runs here on a short-lived loop of the calling thread.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import os

from franklinwh_ha_notify import HAInstance, SUPERVISOR_CORE, Target, send

log = logging.getLogger(__name__)


def _service(name: str) -> str:
    """Both forms turn up in the wild; HA's notify domain wants the bare name."""
    return name.split(".", 1)[1] if name.startswith("notify.") else name


def _instance(row: dict) -> HAInstance:
    base = (row.get("base_url") or "").rstrip("/")
    if base in (SUPERVISOR_CORE, SUPERVISOR_CORE + "/api"):
        # The Supervisor's token changes on every add-on restart: read it live.
        return HAInstance(row["id"], SUPERVISOR_CORE,
                          lambda: os.environ.get("SUPERVISOR_TOKEN") or row.get("token") or "",
                          row.get("name") or "")
    return HAInstance(row["id"], base, row.get("token") or "", row.get("name") or "")


def _run(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    # Called on a thread that already runs a loop: send from a fresh thread instead of
    # blocking that loop on itself.
    with concurrent.futures.ThreadPoolExecutor(1) as ex:
        return ex.submit(asyncio.run, coro).result()


def switched_on(settings) -> bool:
    return bool(getattr(settings, "ha_notify", True))


def push(store, settings, event: str, title: str, message: str, *,
         devices: list[dict] | None = None, ignore_switch: bool = False) -> dict:
    """Send to ``devices`` (default: every enabled saved device) and log each delivery.

    ``ignore_switch`` is for an explicit test the user pressed. Returns
    ``{"sent", "total", "skipped", "results": [{device_id, alias, ok, error}]}``.
    """
    if devices is None:
        devices = [d for d in store.notify_devices() if d.get("enabled")]
    if not ignore_switch and not switched_on(settings):
        store.log_notify(event, title=title, message=message,
                         device="(push notifications are off)", ok=None)
        return {"sent": 0, "total": 0, "skipped": "push notifications are off", "results": []}
    if not devices:
        store.log_notify(event, title=title, message=message, device="(no devices)", ok=None)
        return {"sent": 0, "total": 0, "skipped": "no devices", "results": []}

    inst_rows = {i["id"]: i for i in store.ha_instances()}
    instances, targets, results, by_key = {}, [], [], {}
    for d in devices:
        alias = d.get("alias") or d.get("id") or d.get("service")
        inst = inst_rows.get(d.get("instance_id"))
        if inst is None:
            results.append({"device_id": d.get("id"), "alias": alias, "ok": False,
                            "error": "missing instance"})
            store.log_notify(event, title=title, message=message, device=alias, ok=False)
            continue
        # A disabled instance switches its devices off without each one being disabled.
        if not inst.get("enabled", 1):
            results.append({"device_id": d.get("id"), "alias": alias, "ok": None,
                            "error": "instance disabled"})
            store.log_notify(event, title=title, message=message,
                             device=f"{alias} (instance disabled)", ok=None)
            continue
        ha = _instance(inst)
        if not ha.bearer():
            results.append({"device_id": d.get("id"), "alias": alias, "ok": False,
                            "error": "no token configured for this instance"})
            store.log_notify(event, title=title, message=message, device=alias, ok=False)
            continue
        instances[inst["id"]] = ha
        t = Target(inst["id"], _service(d["service"]), alias)
        targets.append(t)
        by_key[t.key] = (d, alias)

    res = _run(send(instances, targets, title, message)) if targets else None
    for dl in (res.deliveries if res else []):
        d, alias = by_key[dl.target]
        results.append({"device_id": d.get("id"), "alias": alias, "ok": dl.ok,
                        **({"error": dl.error} if dl.error else {})})
        store.log_notify(event, title=title, message=message, device=alias, ok=dl.ok)
    sent = sum(1 for r in results if r["ok"])
    return {"sent": sent, "total": len(devices), "skipped": None, "results": results}
