"""Troubleshoot an aGate that is unreachable or on 4G (#614).

A LAN check alone cannot see "the aGate is on 4G": on 2026-11-13 the aGate kept answering
on :9000 the whole time its internet went over 4G (Wi-Fi associated, gateway 0.0.0.0). Two
sources together localise it:

* the aGate's own report over the LAN, 1118 ``currentNetType`` — read by the poller every
  ``NET_EVERY_S`` (:func:`note_local_network`);
* the FranklinWH cloud, asked on demand by the Troubleshoot panel
  (``cloud_status.read_connectivity`` → the library's ``get_network_state()``).

Either one publishes the ``AGATE_ON_4G`` fact; the alert monitor applies the thresholds.
Reconnect to Wi-Fi is the library's ``switch_to_wifi(ssid, password=None)``: the bridge
never holds, logs or shows a Wi-Fi password.
"""
from __future__ import annotations

import logging
import threading
import time

from . import alerts

log = logging.getLogger(__name__)

#: The library's interface keys, as the panel names them.
LABELS = {"wifi": "Wi-Fi", "eth0": "Ethernet", "eth1": "Ethernet", "4g": "4G"}


def note_local_network(gateway_id: str, lan_ok: bool, net_state: dict | None,
                       now: float | None = None) -> None:
    """The poller's local network read: on 4G while the poll answers is the warning.
    With the LAN down this is not the fault (GATEWAY_UNREACHABLE is), so the fact is
    good: one fault, one alert."""
    via = (net_state or {}).get("net_cloud_via")
    if lan_ok and via is None:
        return                       # not read this cycle: the last fact stands
    alerts.set_condition(gateway_id, "AGATE_ON_4G", bool(lan_ok and via == "4G"), now=now,
                         detail="The aGate answers on your LAN, but its internet goes over "
                                "4G (its own report, 1118). Its Wi-Fi has no route out — "
                                "check the router, or reconnect it to Wi-Fi.")


def lan_state(store, gateway_id: str) -> dict:
    """The bridge's own link to the aGate on :9000, as the poller recorded it."""
    row = None
    if store is not None:
        try:
            row = store.link_state(gateway_id)
        except Exception:  # noqa: BLE001 — a missing record is "unknown", not an error
            row = None
    st = (row or {}).get("state") or "unknown"
    return {"state": st, "up": st == "up", "last_ok_ts": (row or {}).get("last_ok_ts"),
            "down_since_ts": (row or {}).get("down_since_ts"),
            "last_error": (row or {}).get("last_error") or None}


def cloud_block(got: dict | None, *, reason: str | None = None) -> dict:
    """The cloud's answer, trimmed to what the panel shows: no MAC, no IP, no password."""
    if got is None:
        return {"available": False, "reason": reason, "reachable": None, "connection": None,
                "label": None, "fallbacks": []}
    if not got.get("reachable"):
        return {"available": True, "reason": None, "reachable": False, "connection": None,
                "label": None, "fallbacks": [], "detail": got.get("detail")}
    net = got.get("network") or {}
    key = (net.get("active") or {}).get("key")
    conn = "ethernet" if key in ("eth0", "eth1") else key
    return {"available": True, "reason": None, "reachable": True, "connection": conn,
            "label": LABELS.get(key or "", None),
            "fallbacks": [LABELS.get(k, k) for k in (net.get("available_transports") or [])
                          if k != key]}


def verdict(lan: dict, cloud: dict, local_via: str | None = None) -> dict:
    """One sentence for the banner and the panel, from the LAN and the cloud together.
    ``local_via`` is the aGate's own 1118 report, used while the cloud is not available."""
    up = bool(lan.get("up"))
    conn = cloud.get("connection")
    if cloud.get("available") and cloud.get("reachable") is False:
        if up:
            return {"code": "no_cloud", "severity": "warning",
                    "text": "aGate answers on your LAN, but the FranklinWH cloud can't reach "
                            "it — check your internet connection."}
        return {"code": "offline", "severity": "critical",
                "text": "aGate is offline everywhere: not on your LAN and not on the "
                        "FranklinWH cloud. Check its power, then your internet."}
    if conn is None and up and local_via == "4G":
        conn = "4g"
    if conn == "4g":
        if up:
            return {"code": "on_4g", "severity": "warning",
                    "text": "aGate is using 4G — Wi-Fi has no internet. The bridge still "
                            "reaches it on your LAN."}
        return {"code": "left_wifi", "severity": "critical",
                "text": "aGate is online via 4G (cloud) but not on your LAN — it has left "
                        "Wi-Fi."}
    if conn in ("wifi", "ethernet"):
        how = LABELS["wifi" if conn == "wifi" else "eth0"]
        if up:
            return {"code": "online", "severity": "ok",
                    "text": f"aGate is online on your LAN, via {how}."}
        return {"code": "lan_only", "severity": "critical",
                "text": f"aGate is online via {how} (cloud), but the bridge can't reach it "
                        "on your LAN — check its address and the bridge's network."}
    if up:
        return {"code": "online_lan", "severity": "ok",
                "text": "aGate answers on your LAN."}
    return {"code": "unreachable", "severity": "critical",
            "text": "aGate isn't answering on your LAN. Without the FranklinWH cloud the "
                    "bridge can't tell whether it left Wi-Fi or lost power."}


def note_cloud_verdict(gateway_id: str, v: dict, cloud: dict) -> None:
    """The cloud's answer publishes the same fact as the poller's local read — only when
    the cloud actually answered."""
    if cloud.get("reachable"):
        alerts.set_condition(gateway_id, "AGATE_ON_4G", v["code"] == "on_4g",
                             detail="The aGate answers on your LAN, but the FranklinWH cloud "
                                    "says its internet goes over 4G. Its Wi-Fi has no route "
                                    "out — check the router, or reconnect it to Wi-Fi.")


def health(check: dict, lan: dict, poll_interval_s: float, now: float | None = None,
           port: int = 9000) -> list[dict]:
    """The panel's four pass/fail rows from :func:`client.link_check` and the link record.
    ``ok`` None is "not known", shown as such rather than as a failure."""
    ts = float(now if now is not None else time.time())
    aws = check.get("aws_status")
    last = lan.get("last_ok_ts")
    fresh = bool(last) and ts - float(last) <= max(3 * float(poll_interval_s or 30), 120)
    return [
        {"key": "lan", "label": "LAN reachability (ping)", "ok": bool(check.get("ping")),
         "detail": "answers ping" if check.get("ping") else "no ping reply"},
        {"key": "local_api", "label": f"Local API (:{port})", "ok": bool(check.get("local_api")),
         "detail": (f"signed in, {check['latency_ms']} ms" if check.get("local_api")
                    else f"no answer on :{port} — {check.get('error') or 'unreachable'}")},
        {"key": "cloud_link", "label": "Cloud link (aGate's own report)",
         "ok": None if aws is None else aws == 1,
         "detail": ("not read — the local API didn't answer" if aws is None
                    else "connected to the FranklinWH cloud" if aws == 1
                    else "not connected to the FranklinWH cloud")},
        {"key": "last_good", "label": "Last good poll", "ok": fresh, "ts": last,
         "detail": "never" if not last else ("recent" if fresh else "not recent")},
    ]


# ── Reconnect to Wi-Fi: one job per gateway, run off the request ─────────────────
#: The library's verify loop waits up to 180 s, longer than a proxy may hold a request,
#: so the switch runs in a thread and the dialog polls for its result.
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


def reset() -> None:
    """Test hook."""
    with _jobs_lock:
        _jobs.clear()


def job(gateway_id: str) -> dict:
    with _jobs_lock:
        return dict(_jobs.get(gateway_id) or {"state": "idle", "result": None})


def outcome(res: dict) -> dict:
    """The library's section 5.3 result as the dialog shows it. A refused preflight and a
    verify timeout come back, not raised; both send the user to the app."""
    pre = res.get("preflight") or {}
    ver = res.get("verification") or {}
    if not pre.get("passed", False):
        return {"ok": False, "outcome": "refused", "use_app": True,
                "reasons": list(pre.get("reasons") or []),
                "message": "Not sent: the check before writing refused it, so nothing was "
                           "changed on the aGate."}
    if ver.get("state") == "connected":
        return {"ok": True, "outcome": "connected", "use_app": False,
                "elapsed_s": ver.get("elapsed_s"),
                "message": f"The aGate is back on Wi-Fi (confirmed after "
                           f"{round(float(ver.get('elapsed_s') or 0))} s)."}
    return {"ok": False, "outcome": "timeout" if ver.get("state") == "timeout" else "unconfirmed",
            "use_app": True, "elapsed_s": ver.get("elapsed_s"),
            "message": "The aGate accepted the change, but it was not confirmed back on Wi-Fi. "
                       "It keeps 4G meanwhile; it was not retried."}


def start(gateway_id: str, run, on_done=None) -> bool:
    """Start ``run()`` (which returns the library result) for this gateway; ``on_done``
    gets the shown result. False while one is already running."""
    with _jobs_lock:
        if (_jobs.get(gateway_id) or {}).get("state") == "running":
            return False
        _jobs[gateway_id] = {"state": "running", "result": None, "started_ts": time.time()}

    def _go():
        try:
            res = outcome(run())
        except ValueError:
            # The library's refusal to reuse a password for any other network.
            res = {"ok": False, "outcome": "ssid_changed", "use_app": True,
                   "message": "The Wi-Fi network stored on the aGate has changed, so there "
                              "is no stored password to reuse. Nothing was sent."}
        except Exception as e:  # noqa: BLE001 — shown in the dialog, never raised
            res = {"ok": False, "outcome": "error", "use_app": True,
                   "message": f"The FranklinWH cloud didn't complete it: {type(e).__name__}: {e}"}
        log.log(logging.INFO if res["ok"] else logging.WARNING,
                "[%s] Reconnect to Wi-Fi: %s", gateway_id, res["outcome"])
        with _jobs_lock:
            _jobs[gateway_id] = {**_jobs[gateway_id], "state": "done", "result": res,
                                 "ended_ts": time.time()}
        if on_done is not None:
            try:
                on_done(res)
            except Exception as e:  # noqa: BLE001 — bookkeeping never loses the result
                log.debug("[%s] Reconnect to Wi-Fi: not recorded: %s", gateway_id, e)

    threading.Thread(target=_go, name=f"wifi-reconnect-{gateway_id}", daemon=True).start()
    return True
