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


class Recorder:
    """Runs at most one recording session at a time."""

    def __init__(self):
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._state: dict = {"active": False, "session_id": None, "captured": 0,
                             "planned": 0, "errors": 0, "last_error": None}

    def status(self) -> dict:
        with self._lock:
            return dict(self._state)

    def start(self, store, fetch, *, samples: int, interval_s: float,
              gateway_id=None, apower_sn=None, dev_id: int = 1,
              label: str | None = None, purge: tuple | None = None) -> dict:
        """Begin a session. ``fetch()`` returns the 1705 cells dict per snapshot.
        ``purge`` is (keep_days, max_mb): run the recordings purge when it ends.

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
                           "planned": samples, "errors": 0, "last_error": None}
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._run, args=(store, fetch, sid, samples, interval_s, purge),
                daemon=True, name=f"bms-record-{sid}")
            self._thread.start()
            return dict(self._state)

    def stop(self) -> dict:
        """Ask the session to finish early. The thread closes it out."""
        self._stop.set()
        return self.status()

    def _run(self, store, fetch, sid, samples, interval_s, purge=None):
        try:
            for _ in range(samples):
                if self._stop.is_set():
                    break
                try:
                    cells = fetch()
                    if cells:
                        store.add_bms_sample(sid, cells)
                        with self._lock:
                            self._state["captured"] += 1
                except Exception as e:  # noqa: BLE001
                    # A dropped read must not abort the session — this link drops
                    # routinely and a partial session is still useful.
                    with self._lock:
                        self._state["errors"] += 1
                        self._state["last_error"] = str(e)
                    log.warning("bms record: sample failed: %s", e)
                if self._stop.wait(interval_s):
                    break
        finally:
            try:
                store.end_bms_session(sid)
            except Exception as e:  # noqa: BLE001
                log.warning("bms record: could not close session %s: %s", sid, e)
            with self._lock:
                self._state["active"] = False
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
