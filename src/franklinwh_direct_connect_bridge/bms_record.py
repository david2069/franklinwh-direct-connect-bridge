"""
BMS recording sessions — bounded bursts of full per-cell snapshots.

The Battery tab's live trend lives in the browser and dies with the page. A
*session* is the persisted equivalent: N snapshots at a fixed interval, stored
whole (all 16 cell voltages + temperatures) so they can be charted and compared
later.

Runs in a background thread rather than the poll loop: recording is a
user-initiated burst at a much finer interval than the 30s poll, and it must not
perturb the poller — which is the thing keeping the long-run history.

Only one session runs at a time. Recording a second while one is active would
double the device session rate on a link that is already marginal.
"""

from __future__ import annotations

import logging
import threading
import time

log = logging.getLogger(__name__)

#: Guardrails. The aGate is slow and shared, so nothing reads it faster than every 5 s.
#: A recording may run for a day (owner, 2026-11-11: Record from the live trend, and
#: scheduled recordings), so the sample cap is a day at that floor; the purge limits
#: in Settings keep what is stored in check.
MIN_INTERVAL_S = 5.0
MAX_SAMPLES = 24 * 3600 // int(MIN_INTERVAL_S)
#: A failed read doesn't use up a planned sample, so a recording carries on once the
#: aGate is back (owner, 2026-11-14). It gives up after this long with no good read.
GIVE_UP_AFTER_S = 3600


class Recorder:
    """Runs at most one recording session at a time."""

    def __init__(self):
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._state: dict = {"active": False, "session_id": None, "captured": 0,
                             "planned": 0, "errors": 0, "last_error": None,
                             "end_reason": None}
        self._stop_by: str | None = None

    def status(self) -> dict:
        with self._lock:
            return dict(self._state)

    def start(self, store, fetch, *, samples: int, interval_s: float,
              gateway_id=None, apower_sn=None, dev_id: int = 1,
              label: str | None = None, purge: tuple | None = None,
              by: str = "unknown") -> dict:
        """Begin a session. ``fetch()`` returns the 1705 cells dict per snapshot.
        ``purge`` is (keep_days, max_mb): run the recordings purge when it ends.
        ``by`` says who started it, for the log.

        Raises ValueError for out-of-range parameters or if one is already running —
        the caller maps that to 409/422 rather than silently queuing.
        """
        if interval_s < MIN_INTERVAL_S:
            raise ValueError(f"interval must be >= {MIN_INTERVAL_S:g}s "
                             f"(the aGate is slow and shared)")
        if not (1 <= samples <= MAX_SAMPLES):
            raise ValueError(f"samples must be 1..{MAX_SAMPLES}")
        with self._lock:
            if self._state["active"]:
                raise ValueError("a recording session is already running")
            sid = store.start_bms_session(
                gateway_id=gateway_id, apower_sn=apower_sn, dev_id=dev_id,
                interval_s=interval_s, planned=samples, label=label)
            self._state = {"active": True, "session_id": sid, "captured": 0,
                           "planned": samples, "errors": 0, "last_error": None,
                           "end_reason": None}
            self._stop_by = None
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._run, args=(store, fetch, sid, samples, interval_s, purge),
                daemon=True, name=f"bms-record-{sid}")
            self._thread.start()
            log.info("bms record: session %s started by %s: %d sample(s) every %gs, unit %s%s",
                     sid, by, samples, interval_s, dev_id, f" ({label})" if label else "")
            return dict(self._state)

    def stop(self, by: str = "unknown") -> dict:
        """Ask the session to finish early. The thread closes it out."""
        with self._lock:
            if self._state["active"] and not self._stop.is_set():
                self._stop_by = by
                log.info("bms record: session %s stop requested by %s",
                         self._state["session_id"], by)
        self._stop.set()
        return self.status()

    def _run(self, store, fetch, sid, samples, interval_s, purge=None):
        captured, down_since, reason = 0, None, "completed"
        try:
            while captured < samples:
                if self._stop.is_set():
                    break
                try:
                    cells = fetch()
                    if not cells:
                        raise ValueError("no cell data in the reply")
                    store.add_bms_sample(sid, cells)
                    captured += 1
                    with self._lock:
                        self._state["captured"] = captured
                    if down_since is not None:
                        log.info("bms record: session %s: aGate back after %.0fs, recording "
                                 "resumes", sid, time.monotonic() - down_since)
                        down_since = None
                except Exception as e:  # noqa: BLE001
                    # A dropped read must not abort the session — this link drops
                    # routinely. It doesn't count toward the planned samples either.
                    with self._lock:
                        self._state["errors"] += 1
                        self._state["last_error"] = str(e)
                    log.warning("bms record: session %s: sample failed: %s", sid, e)
                    if down_since is None:
                        down_since = time.monotonic()
                    elif time.monotonic() - down_since >= GIVE_UP_AFTER_S:
                        reason = (f"aGate unreachable for "
                                  f"{(time.monotonic() - down_since) / 60:.0f} min")
                        break
                if self._stop.wait(interval_s):
                    break
            if self._stop.is_set() and captured < samples:
                reason = f"stopped by {self._stop_by or 'unknown'}"
        except Exception as e:  # noqa: BLE001
            reason = f"error: {e}"
            raise
        finally:
            try:
                store.end_bms_session(sid, reason=reason)
            except Exception as e:  # noqa: BLE001
                log.warning("bms record: could not close session %s: %s", sid, e)
            with self._lock:
                self._state["active"] = False
                self._state["end_reason"] = reason
                errors = self._state["errors"]
            log.info("bms record: session %s ended: %s (%d of %d sample(s), %d failed read(s))",
                     sid, reason, captured, samples, errors)
            if purge:
                try:
                    store.prune_bms(*purge)
                except Exception as e:  # noqa: BLE001 — the recording itself is saved
                    log.warning("bms record: purge after session %s failed: %s", sid, e)


def due(schedules: list[dict], now) -> list[dict]:
    """The scheduled recordings to start at ``now`` (a naive datetime on the site's
    clock): switched on, today is one of its weekdays (Monday = 0), not yet run today,
    and ``now`` is inside its window. Each comes back with ``samples`` for what is left
    of the window, so a bridge that starts late records the rest, not a full window."""
    today = now.strftime("%Y-%m-%d")
    out = []
    for sc in schedules:
        if not sc.get("enabled") or now.weekday() not in (sc.get("days") or []):
            continue
        if sc.get("last_run") == today:
            continue
        try:
            hh, mm = (int(x) for x in str(sc["at"]).split(":"))
        except (KeyError, ValueError):
            continue
        start = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        left = (start - now).total_seconds() + int(sc["minutes"]) * 60
        if now < start or left <= 0:
            continue
        samples = min(MAX_SAMPLES, int(left // float(sc["interval_s"])))
        if samples >= 1:
            out.append(dict(sc, samples=samples))
    return out


#: Process-global recorder — one aGate, one session at a time.
_recorder = Recorder()


def get_recorder() -> Recorder:
    return _recorder
