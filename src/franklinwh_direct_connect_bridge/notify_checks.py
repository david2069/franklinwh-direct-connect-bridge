"""Notifications check (#464): can a critical alert reach Home Assistant and the phones?

Each line is ``{id, label, status, detail, fix}`` with ``status`` one of ``pass``,
``fail`` or ``unset`` (not set up). The fix says what to do on this bridge. Served by
``GET /api/notify/checks`` for Settings → Notifications, and, redacted, in Support info.

Also keeps the last **Test with buttons** result, which used to live only in the browser.
"""
from __future__ import annotations

import json
import re
import time

PASS, FAIL, UNSET = "pass", "fail", "unset"

#: app_config key of the last Test with buttons result.
LAST_TEST_KEY = "notify_test_buttons_last"


def _line(id_: str, label: str, status: str, detail: str, fix: str = "") -> dict:
    return {"id": id_, "label": label, "status": status, "detail": detail,
            "fix": "" if status == PASS else fix}


# ── the last Test with buttons ─────────────────────────────────────────────────
def record_test(store, *, ok: bool | None, result: str, device: str = "",
                request_id: str = "", now: float | None = None) -> None:
    """Keep the last Test with buttons result: ``ok`` True (tapped), False (not sent, no
    reply) or None (sent, waiting for a tap). Never raises."""
    if store is None:
        return
    try:
        store.set_config(LAST_TEST_KEY, json.dumps({
            "ts": float(now if now is not None else time.time()), "ok": ok,
            "result": result, "device": device, "request_id": request_id}))
    except Exception:  # noqa: BLE001 — a record, never a failure
        pass


def last_test(store) -> dict | None:
    try:
        raw = store.get_config(LAST_TEST_KEY) if store is not None else None
        return json.loads(raw) if raw else None
    except Exception:  # noqa: BLE001
        return None


def test_tapped(store, request_id: str, answer: str) -> None:
    """A tap on the test: recorded when it answers the test the record is waiting on."""
    last = last_test(store) or {}
    if last.get("request_id") == request_id:
        record_test(store, ok=True, result=f"tapped {answer}", device=last.get("device", ""),
                    request_id=request_id)


def test_expired(store, request_id: str) -> None:
    last = last_test(store) or {}
    if last.get("request_id") == request_id and last.get("ok") is None:
        record_test(store, ok=False, result="no reply", device=last.get("device", ""),
                    request_id=request_id)


# ── the checks ─────────────────────────────────────────────────────────────────
def _probe_target(t: dict) -> dict:
    from . import ha_instances
    base = t["base"][:-len("/api")] if t["base"].endswith("/api") else t["base"]
    return ha_instances.probe(base, t["token"])


def _where(t: dict) -> str:
    return {"instance": f"HA instance \"{t['name']}\"",
            "supervisor": "this add-on's Home Assistant (Supervisor)",
            "environment": "HA_URL / HA_TOKEN from the environment"}.get(t["source"], "")


def checks(store, settings) -> dict:
    """Every check line, in order. Calls Home Assistant once (the probe)."""
    from . import actionable, notify_engine
    from .notify import Notifier
    lines: list[dict] = []
    t = Notifier(settings).target_info()
    on = bool(settings.ha_notify)

    lines.append(_line(
        "push_switch", "Push notifications switch", PASS if on else FAIL,
        "On" if on else "Off: no Home Assistant notification and no push is sent",
        "Switch on Push notifications at the top of this card."))

    if t["source"] == "none":
        lines.append(_line(
            "ha_instance", "Default HA instance", UNSET, "No HA instance set up",
            "Add one under HA Instances below (URL and long-lived token), and make it the "
            "default."))
    else:
        p = _probe_target(t)
        what = _where(t)
        lines.append(_line(
            "ha_instance", "Default HA instance", PASS if p.get("ok") else FAIL,
            f"{what}: reachable, token accepted" if p.get("ok")
            else f"{what}: {p.get('error') or 'not reachable'}",
            "Token rejected: create a new long-lived token in Home Assistant (profile → "
            "Security) and Edit the instance below." if p.get("error") == "token rejected"
            else "Check the instance's Base URL from this bridge's network (Edit → Test), "
                 "and that Home Assistant is running."))

    rows = [r for r in (store.ha_instances() if store else []) if r.get("enabled", 1)]
    n = actionable.notifier()
    status = {}
    if n is not None:
        try:
            status = n.listener_status()
        except Exception:  # noqa: BLE001
            status = {}
    if not rows:
        lines.append(_line("listener", "Button taps listener", UNSET,
                           "No enabled HA instance to listen on",
                           "Add an HA instance under HA Instances below."))
    for r in rows:
        name = r.get("name") or r["id"]
        st = status.get(r["id"])
        if n is None:
            ok, detail = False, "Notifications with buttons are not running"
        elif st is None:
            ok, detail = False, "Not listening"
        else:
            ok = bool(st.get("connected"))
            detail = "Connected" if ok else (st.get("error") or "Not connected yet")
        lines.append(_line(
            f"listener:{r['id']}", f"Button taps listener: {name}", PASS if ok else FAIL,
            detail, "Check the instance's URL and token (Edit → Test). Taps arrive over Home "
            "Assistant's WebSocket; if the error stays, see Logs."))

    live = {r["id"] for r in rows}
    devices = [d for d in (store.notify_devices() if store else [])
               if d.get("enabled") and d["instance_id"] in live]
    phones = [d for d in devices if d["service"].removeprefix("notify.").startswith("mobile_app_")]
    if phones:
        lines.append(_line("phones", "Phones (mobile_app_*)", PASS,
                           f"{len(phones)} enabled phone(s)"))
    else:
        lines.append(_line(
            "phones", "Phones (mobile_app_*)", FAIL if devices else UNSET,
            f"{len(devices)} enabled device(s), none a mobile_app_* phone" if devices
            else "No enabled notification device",
            "Install the Home Assistant Companion app on a phone, sign in, then + Add device "
            "below and pick its notify.mobile_app_* service. Only phones show buttons."))

    last = last_test(store)
    if not last:
        lines.append(_line("last_test", "Last Test with buttons", UNSET, "Never run",
                           "Press Test with buttons on a phone's row below, then tap Yes or No "
                           "on the phone."))
    else:
        lines.append(_line(
            "last_test", "Last Test with buttons",
            PASS if last.get("ok") else FAIL if last.get("ok") is False else UNSET,
            last.get("result") or "", "Run Test with buttons again. Not sent: check the "
            "lines above. No reply: check the listener line and that the phone shows "
            "notifications from the Companion app.") | {"ts": last.get("ts")})

    ids = notify_engine.send_to_ids(store, "alert") if store else None
    to = actionable.targets(store, ids) if store else []
    reach = [x for x in to if x.buttons]
    if not on:
        lines.append(_line("route", "Where critical alerts go", FAIL,
                           "Only the bridge UI: Push notifications is off",
                           "Switch on Push notifications."))
    elif t["source"] == "none" and not reach:
        lines.append(_line("route", "Where critical alerts go", UNSET,
                           "Only the bridge UI", "Add an HA instance and a phone below."))
    else:
        where = _where(t) if t["source"] != "none" else "no Home Assistant notification"
        dev = f"{len(reach)} phone(s) with Acknowledge" if reach else "no phone"
        lines.append(_line("route", "Where critical alerts go", PASS if reach else FAIL,
                           f"{where}; {dev}",
                           "Add a phone below, or under Send to for Critical alerts choose "
                           "a phone that is switched on.") | {"source": t["source"]})
    return {"checks": lines, "source": t["source"],
            "summary": {s: sum(1 for x in lines if x["status"] == s)
                        for s in (PASS, FAIL, UNSET)}}


_URL = re.compile(r"\b[a-z][a-z0-9+.-]*://\S+", re.I)
_IP = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?\b")


def redact(text: str) -> str:
    return _IP.sub("<ip>", _URL.sub("<url>", text or ""))


_FIXED = {"Notifications with buttons are not running", "Not listening",
          "No enabled HA instance to listen on"}


def for_support(result: dict) -> list[dict]:
    """The check lines for Support info: no names, URLs, addresses or tokens."""
    out = []
    for x in result.get("checks", []):
        row = {"check": x["id"].split(":", 1)[0], "status": x["status"]}
        if x["id"] in ("ha_instance", "route"):
            row["source"] = result.get("source")
        elif x["id"].startswith("listener"):
            # Not the error itself: its text can name a host.
            row["detail"] = x["detail"] if x["detail"] in _FIXED else (
                "connected" if x["status"] == PASS else "not connected")
        elif x["id"] == "last_test":
            row["detail"] = redact(x["detail"])
        elif x["id"] in ("push_switch", "phones"):
            row["detail"] = x["detail"]
        if x["status"] == FAIL and x["id"] == "ha_instance":
            row["detail"] = "token rejected" if "token rejected" in x["detail"] else "not reachable"
        out.append(row)
    return out
