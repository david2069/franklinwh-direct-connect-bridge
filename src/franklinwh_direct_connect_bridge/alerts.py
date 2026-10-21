"""Stored alerts (#271), built to the shared spec v1 on franklinwh-modbus-bridge#324.

Two kinds of record:

* an **event** (a command refused, a schedule that failed) is raised inline at its source
  and stays open until it is acknowledged;
* a **condition** (gateway unreachable, live data missing) is active while the fault
  lasts and gets a ``resolved_ts`` when it clears. Acknowledging it stops the modal, not
  the indicator.

Sources do not decide when a condition opens. They publish a FACT — "this is bad now",
"this is good now" — with :func:`set_condition`, and the :class:`AlertMonitor` applies
the catalogue's open/resolve thresholds every 15 s. That keeps the thresholds in one
place, so a 30 s poll and a 5 s supervisor pass cannot disagree about what 5 minutes is.

Delivery goes through an outbox (``alert_deliveries``). The alert row is written first;
the Home Assistant notification is sent afterwards by the monitor, retried with back-off.
A failed delivery never blocks or loses the alert — the bridge stays the record.

Every raise, merge, resolve and acknowledgement is also one line in the app log (WARNING
for a raise, INFO for a resolve or an acknowledgement), whether or not it was delivered.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time

from . import workers as _workers

log = logging.getLogger("franklinwh_direct_connect_bridge.alerts")

EVENT = "event"
CONDITION = "condition"
WARNING = "warning"
CRITICAL = "critical"

#: The shared code catalogue (spec §2). `open_s` / `resolve_s` are how long a condition
#: must be continuously bad / good before it opens / resolves. Fixed defaults for now.
#: WORKER_STALLED's threshold is the supervisor's own staleness verdict, so the monitor
#: opens and resolves it as soon as that verdict changes.
CATALOGUE: dict[str, dict] = {
    "GATEWAY_UNREACHABLE": {"kind": CONDITION, "severity": CRITICAL,
                            "open_s": 300, "resolve_s": 120,
                            "title": "aGate unreachable"},
    "LIVE_DATA_MISSING": {"kind": CONDITION, "severity": CRITICAL,
                          "open_s": 120, "resolve_s": 60,
                          "title": "Live data missing"},
    "DATA_MISSING_PARTIAL": {"kind": CONDITION, "severity": WARNING,
                             "open_s": 120, "resolve_s": 60,
                             "title": "Some live data missing"},
    "MQTT_DOWN": {"kind": CONDITION, "severity": WARNING,
                  "open_s": 300, "resolve_s": 120,
                  "title": "MQTT broker disconnected"},
    "HA_UNREACHABLE": {"kind": CONDITION, "severity": WARNING,
                       "open_s": 300, "resolve_s": 120,
                       "title": "Home Assistant unreachable"},
    "WORKER_STALLED": {"kind": CONDITION, "severity": CRITICAL,
                       "open_s": 0, "resolve_s": 0,
                       "title": "Background worker stalled"},
    "COMMAND_REFUSED": {"kind": EVENT, "severity": CRITICAL,
                        "title": "Command refused"},
    "COMMAND_UNCONFIRMED": {"kind": EVENT, "severity": CRITICAL,
                            "title": "Command not confirmed"},
    "WRITE_IGNORED": {"kind": EVENT, "severity": CRITICAL,
                      "title": "Write ignored by the aGate"},
    "SCHEDULE_FAILED": {"kind": EVENT, "severity": CRITICAL,
                        "title": "Scheduled action failed"},
    "RESTART_DURING_COMMAND": {"kind": EVENT, "severity": CRITICAL,
                               "title": "Bridge restarted during a command"},
    "EXTERNAL_SETPOINT": {"kind": EVENT, "severity": WARNING,
                          "title": "Setpoint changed outside the bridge"},
    "INTERNAL_ERROR": {"kind": EVENT, "severity": WARNING,
                       "title": "Internal error"},
}

#: Events of the same code within this window merge into the open, unacknowledged alert.
MERGE_WINDOW_S = 600
#: INTERNAL_ERROR is raised at most once per code per hour; repeats are counted on it.
INTERNAL_ERROR_EVERY_S = 3600
#: Who may acknowledge, recorded as `source:<name>`. This bridge has no users.
ACK_SOURCES = ("ui", "api", "ha")
#: The Home Assistant persistent notification's id, so a later dismiss can find it.
HA_NOTIFICATION_ID = "fwh_dc_alert_{id}"
#: Outbox channels.
CH_HA_CREATE = "ha_persistent"
CH_HA_DISMISS = "ha_dismiss"
#: Monitor cadence and the delivery back-off (15 s → 10 min).
MONITOR_EVERY_S = 15.0
RETRY_BASE_S = 15.0
RETRY_CAP_S = 600.0
WORKER_NAME = "alert-monitor"

# ── facts: what the sources last said, in memory ────────────────────────────────
# (gateway_id, code) -> {"bad": bool, "since": ts the current state began, "detail": str}
_facts: dict[tuple[str, str], dict] = {}
_facts_lock = threading.Lock()
#: Outbox back-off is held here rather than in the table: after a restart every owed
#: delivery is simply tried again, which is what a restart should do.
_next_try: dict[tuple[int, str], float] = {}


def set_condition(gateway_id: str, code: str, bad: bool, now: float | None = None,
                  detail: str = "") -> None:
    """Publish one fact about a condition. Cheap, never raises, never touches the DB:
    the monitor turns facts into alerts. ``since`` moves only when the fact flips, so
    a run of bad reports is measured from its first one."""
    if CATALOGUE.get(code, {}).get("kind") != CONDITION:
        return
    ts = float(now if now is not None else time.time())
    key = (gateway_id or "", code)
    with _facts_lock:
        cur = _facts.get(key)
        if cur is None or cur["bad"] != bool(bad):
            _facts[key] = {"bad": bool(bad), "since": ts, "detail": detail}
        elif detail:
            cur["detail"] = detail


def facts() -> dict[tuple[str, str], dict]:
    with _facts_lock:
        return {k: dict(v) for k, v in _facts.items()}


def forget_gateway(store, gateway_id: str, now: float | None = None) -> list[int]:
    """A gateway was removed: drop its facts and resolve its open conditions, which no
    source will ever report on again (G1, 2026-10-21: they stayed open for good).
    Events stay as they are — they are history, closed by acknowledgement."""
    ts = float(now if now is not None else time.time())
    with _facts_lock:
        for k in [k for k in _facts if k[0] == gateway_id]:
            del _facts[k]
    closed: list[int] = []
    if store is None or not gateway_id:
        return closed
    for code, spec in CATALOGUE.items():
        if spec.get("kind") != CONDITION:
            continue
        try:
            cur = store.open_condition(gateway_id, code)
            if cur is not None:
                store.resolve_alert(cur["id"], resolved_ts=ts)
                log.info("alert #%s %s %sresolved: gateway removed", cur["id"], code,
                         _gw_tag(gateway_id))
                closed.append(cur["id"])
        except Exception as e:  # noqa: BLE001
            log.warning("alert %s %snot resolved on removal: %s", code, _gw_tag(gateway_id), e)
    return closed


def reset() -> None:
    """Test hook — forget every fact and back-off."""
    with _facts_lock:
        _facts.clear()
    _next_try.clear()


def _gw_tag(gateway_id: str) -> str:
    return f"[{gateway_id}] " if gateway_id else ""


# ── events ──────────────────────────────────────────────────────────────────────
def raise_event(store, gateway_id: str | None, code: str, message: str, *,
                title: str | None = None, severity: str | None = None,
                now: float | None = None) -> int | None:
    """Record one event and return its alert id (None if it could not be recorded).

    Dedup (spec §3): an event of the same code and gateway within MERGE_WINDOW_S of the
    open, unacknowledged one merges into it — count + 1, last_ts moves — rather than
    queueing a second modal. Never raises: an alert must never break the thing it
    reports on."""
    if store is None:
        return None
    try:
        spec = CATALOGUE[code]
        if spec["kind"] != EVENT:
            raise ValueError(f"{code} is not an event")
        ts = float(now if now is not None else time.time())
        gw = gateway_id or ""
        sev = severity or spec["severity"]
        ttl = title or spec["title"]
        if code == "INTERNAL_ERROR":
            prev = store.latest_alert(gw, code)
            if prev and ts - float(prev["opened_ts"]) < INTERNAL_ERROR_EVERY_S:
                store.merge_alert(prev["id"], message=None, now=ts)
                log.warning("alert %s %s(rate-limited, counted on #%s): %s",
                            code, _gw_tag(gw), prev["id"], message)
                return int(prev["id"])
        prev = store.latest_alert(gw, code, unacked=True)
        if prev and ts - float(prev["last_ts"]) <= MERGE_WINDOW_S:
            store.merge_alert(prev["id"], message=message, now=ts)
            log.warning("alert #%s %s %s(repeat %d): %s", prev["id"], code, _gw_tag(gw),
                        int(prev["count"]) + 1, message)
            return int(prev["id"])
        aid = store.insert_alert(gateway_id=gw, kind=EVENT, severity=sev, code=code,
                                 title=ttl, message=message, opened_ts=ts)
        log.warning("alert #%s %s %s%s: %s", aid, code, _gw_tag(gw), sev, message)
        _queue_delivery(store, aid, sev)
        return aid
    except Exception as e:  # noqa: BLE001
        log.warning("alert %s not recorded: %s — %s", code, e, message)
        return None


def _queue_delivery(store, alert_id: int, severity: str) -> None:
    """Critical alerts ALWAYS get a Home Assistant persistent notification (addendum
    §6): independent of any companion device. Written to the outbox, sent later."""
    if severity == CRITICAL:
        try:
            store.queue_delivery(alert_id, CH_HA_CREATE)
        except Exception as e:  # noqa: BLE001
            log.warning("alert #%s delivery not queued: %s", alert_id, e)


# ── conditions ──────────────────────────────────────────────────────────────────
def evaluate(store, now: float | None = None) -> list[dict]:
    """Apply the thresholds to every fact. Returns what changed, as
    ``[{"id", "code", "gateway_id", "change": "opened"|"resolved"}]``."""
    if store is None:
        return []
    ts = float(now if now is not None else time.time())
    changes: list[dict] = []
    for (gw, code), f in facts().items():
        spec = CATALOGUE[code]
        held = ts - float(f["since"])
        try:
            cur = store.open_condition(gw, code)
            if f["bad"]:
                if cur is not None:
                    store.touch_alert(cur["id"], now=ts)
                elif held >= spec["open_s"]:
                    msg = f["detail"] or spec["title"]
                    # Dated from when the fault BEGAN, not from when it crossed the
                    # threshold, so "since 09:54" is the truth.
                    aid = store.insert_alert(
                        gateway_id=gw, kind=CONDITION, severity=spec["severity"],
                        code=code, title=spec["title"], message=msg,
                        opened_ts=float(f["since"]), last_ts=ts)
                    log.warning("alert #%s %s %s%s: %s", aid, code, _gw_tag(gw),
                                spec["severity"], msg)
                    _queue_delivery(store, aid, spec["severity"])
                    changes.append({"id": aid, "code": code, "gateway_id": gw,
                                    "change": "opened"})
            elif cur is not None and held >= spec["resolve_s"]:
                # Resolved at the moment it became good, for the same reason.
                store.resolve_alert(cur["id"], resolved_ts=float(f["since"]))
                log.info("alert #%s %s %sresolved after %ds", cur["id"], code, _gw_tag(gw),
                         int(float(f["since"]) - float(cur["opened_ts"])))
                changes.append({"id": cur["id"], "code": code, "gateway_id": gw,
                                "change": "resolved"})
        except Exception as e:  # noqa: BLE001 — one bad fact must not stop the rest
            log.warning("alert %s %snot evaluated: %s", code, _gw_tag(gw), e)
    return changes


# ── WORKER_STALLED (from the supervisor's own verdict) ─────────────────────────
def _worker_gateway(w) -> str:
    scope = getattr(w, "scope", "") or ""
    return scope.split(":", 1)[1] if scope.startswith("gateway:") else ""


def on_worker_transition(w, reason: str, now: float | None = None) -> None:
    """The supervisor's on_transition hook. UNRESPONSIVE and CRASHED are the stalls;
    the supervisor has already applied its liveness threshold, so this is not
    re-derived — the fact is set and the monitor opens it on its next pass."""
    if w.state in (_workers.WorkerState.UNRESPONSIVE, _workers.WorkerState.CRASHED):
        set_condition(_worker_gateway(w), "WORKER_STALLED", True, now=now,
                      detail=f"{w.name} is {w.state.value}: {reason}")


def check_workers(registry, now: float | None = None) -> None:
    """Clear a WORKER_STALLED fact once every worker in its scope is healthy again
    (beating, or replaced by a restart). Opening stays with the supervisor's hook."""
    stalled = {k for k, f in facts().items() if k[1] == "WORKER_STALLED" and f["bad"]}
    if not stalled:
        return
    bad_scopes = {_worker_gateway(w) for w in registry.all()
                  if w.is_broken or w.beat_is_stale}
    for gw, code in stalled:
        if gw not in bad_scopes:
            set_condition(gw, code, False, now=now)


# ── acknowledgement ─────────────────────────────────────────────────────────────
def ack(store, alert_id: int, source: str, now: float | None = None) -> dict | None:
    """Acknowledge one alert for everyone, recording ``source:<source>`` and when.
    Returns the row (None if it does not exist). A Home Assistant notification that
    was created is dismissed through the outbox; a dismiss in HA is NOT an ack."""
    if source not in ACK_SOURCES:
        raise ValueError(f"source must be one of {', '.join(ACK_SOURCES)}")
    ts = float(now if now is not None else time.time())
    before = store.alert(alert_id)
    if before is None:
        return None
    row = store.ack_alert(alert_id, acked_by=f"source:{source}", now=ts)
    if before.get("acked_ts") is None:
        log.info("alert #%s %s %sacknowledged by source:%s", alert_id, row["code"],
                 _gw_tag(row["gateway_id"]), source)
        if any(d["channel"] == CH_HA_CREATE for d in store.alert_deliveries(alert_id)):
            store.queue_delivery(alert_id, CH_HA_DISMISS)
    return row


# ── delivery (the outbox) ───────────────────────────────────────────────────────
def retry_delay_s(attempts: int) -> float:
    if attempts <= 0:
        return 0.0
    return min(RETRY_CAP_S, RETRY_BASE_S * (2 ** (attempts - 1)))


def _ha_message(row: dict) -> str:
    msg = row.get("message") or ""
    tail = f"\n\n{row['code']}" + (f" · gateway {row['gateway_id']}" if row["gateway_id"] else "")
    return msg + tail + "\nAcknowledge it in the bridge; dismissing it here does not."


def deliver(store, notifier, now: float | None = None) -> int:
    """Send what the outbox owes, honouring each row's back-off. Returns deliveries
    made. Facts about Home Assistant's reachability come from these attempts."""
    ts = float(now if now is not None else time.time())
    sent = 0
    for d in store.pending_deliveries():
        key = (int(d["alert_id"]), d["channel"])
        if _next_try.get(key, 0.0) > ts:
            continue
        row = store.alert(d["alert_id"])
        if row is None:
            continue
        nid = HA_NOTIFICATION_ID.format(id=row["id"])
        if d["channel"] == CH_HA_CREATE:
            if row.get("acked_ts") is not None:
                store.record_delivery(row["id"], d["channel"], ok=False, attempted=False,
                                      error="skipped: acknowledged before delivery", now=ts)
                continue
            service, data = "create", {"notification_id": nid, "title": row["title"],
                                       "message": _ha_message(row)}
        elif d["channel"] == CH_HA_DISMISS:
            created = [x for x in store.alert_deliveries(row["id"])
                       if x["channel"] == CH_HA_CREATE]
            if not created or not created[0].get("delivered_ts"):
                store.record_delivery(row["id"], d["channel"], ok=False, attempted=False,
                                      error="skipped: nothing was delivered to dismiss", now=ts)
                continue
            service, data = "dismiss", {"notification_id": nid}
        else:
            continue
        err = notifier.call_service("persistent_notification", service, data)
        if err.startswith("skipped:"):
            store.record_delivery(row["id"], d["channel"], ok=False, attempted=False,
                                  error=err, now=ts)
            log.info("alert #%s %s: Home Assistant %s %s", row["id"], row["code"],
                     service, err)
            continue
        store.record_delivery(row["id"], d["channel"], ok=not err, error=err, now=ts)
        set_condition("", "HA_UNREACHABLE", bool(err), now=ts,
                      detail=f"Home Assistant did not answer: {err}" if err else "")
        if err:
            _next_try[key] = ts + retry_delay_s(int(d["attempts"]) + 1)
            log.warning("alert #%s %s: Home Assistant %s failed (attempt %d): %s",
                        row["id"], row["code"], service, int(d["attempts"]) + 1, err)
        else:
            _next_try.pop(key, None)
            sent += 1
            log.info("alert #%s %s: Home Assistant notification %s", row["id"], row["code"],
                     "created" if service == "create" else "dismissed")
    return sent


# ── the monitor worker ──────────────────────────────────────────────────────────
#: Prune closed alerts at most this often.
PRUNE_EVERY_S = 3600.0


class AlertMonitor:
    """One pass every MONITOR_EVERY_S: thresholds, worker recovery, delivery, prune.
    Registered as a Worker and beats each cycle; a stale monitor is reported as data
    (/api/status), never as a failed container (RUNTIME_DESIGN decision 4)."""

    def __init__(self, settings, *, store_fn, notifier, registry=None,
                 heartbeat_factory=None) -> None:
        self.settings = settings
        self._store_fn = store_fn
        self.notifier = notifier
        self.registry = registry or _workers.registry
        self._last_prune = 0.0
        self._hb_factory = heartbeat_factory
        self._hb = None
        self._hb_try = float("-inf")
        self._hb_last = float("-inf")

    def heartbeat_once(self, now: float | None = None) -> bool:
        """The bridge-level "Bridge heartbeat" (spec §11), every HEARTBEAT_EVERY_S, sent
        only while MQTT is enabled and this connection is up. Returns True if it beat.
        It rides the monitor's own cycle, so a heartbeat that stops moving means the
        bridge process or its monitor has stopped — not that a gateway has."""
        from .publish import entities
        ts = float(now if now is not None else time.time())
        if not getattr(self.settings, "mqtt_enabled", False):
            self.stop_heartbeat()
            return False
        if self._hb is None and ts - self._hb_try >= entities.HEARTBEAT_EVERY_S:
            self._hb_try = ts
            try:
                if self._hb_factory is None:
                    from .publish.mqtt_publisher import BridgeHeartbeat
                    self._hb_factory = lambda: BridgeHeartbeat(self.settings)
                hb = self._hb_factory()
                hb.start()
                self._hb = hb
            except Exception as e:  # noqa: BLE001 — MQTT_DOWN reports the broker
                log.debug("bridge heartbeat: MQTT connect failed: %s", e)
        if self._hb is None or not self._hb.is_connected():
            return False
        if ts - self._hb_last < entities.HEARTBEAT_EVERY_S:
            return False
        self._hb.beat(ts)
        self._hb_last = ts
        return True

    def stop_heartbeat(self) -> None:
        if self._hb is not None:
            self._hb.stop()
            self._hb = None

    def run_once(self, now: float | None = None) -> None:
        ts = float(now if now is not None else time.time())
        try:
            self.heartbeat_once(now=ts)
        except Exception as e:  # noqa: BLE001 — a heartbeat never stops the monitor
            log.debug("bridge heartbeat failed: %s", e)
        store = self._store_fn()
        if store is None:
            return
        check_workers(self.registry, now=ts)
        evaluate(store, now=ts)
        try:
            deliver(store, self.notifier, now=ts)
        except Exception as e:  # noqa: BLE001 — delivery never stops the monitor
            log.warning("alert delivery pass failed: %s", e)
        if ts - self._last_prune >= PRUNE_EVERY_S:
            self._last_prune = ts
            n = store.prune_alerts(now=ts)
            if n:
                log.info("pruned %d closed alert(s) older than %d days", n,
                         store.ALERT_RETENTION_DAYS)

    async def run(self, stop: asyncio.Event) -> None:
        w = self.registry.register(_workers.Worker(
            name=WORKER_NAME, concern="open, resolve and deliver alerts",
            cadence_s=MONITOR_EVERY_S, restart_class=_workers.RestartClass.FREE,
            kind="task"))
        w._task = asyncio.current_task()
        while not stop.is_set():
            w.beat(state=_workers.WorkerState.RUNNING)
            try:
                await asyncio.to_thread(self.run_once)
            except Exception:  # noqa: BLE001 — the monitor must outlive a bad pass
                log.exception("alert monitor pass failed")
            try:
                await asyncio.wait_for(stop.wait(), timeout=MONITOR_EVERY_S)
            except asyncio.TimeoutError:
                pass
        await asyncio.to_thread(self.stop_heartbeat)
        w.mark_stopped()


def monitor_status(registry=None) -> dict:
    """The monitor's liveness, as data for /api/status."""
    w = (registry or _workers.registry).get(WORKER_NAME)
    if w is None:
        return {"state": "absent", "last_beat_s": None, "stale": True}
    return {"state": w.state.value, "last_beat_s": round(w.beat_age_s, 1),
            "stale": bool(w.beat_is_stale or w.is_broken)}
