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

#: Guardrails. The aGate is slow and shared; a 1s interval or a 10k-sample run
#: would hammer it for no analytical benefit.
MIN_INTERVAL_S = 5.0
MAX_SAMPLES = 500


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
              label: str | None = None) -> dict:
        """Begin a session. ``fetch()`` returns the 1705 cells dict per snapshot.

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
                target=self._run, args=(store, fetch, sid, samples, interval_s),
                daemon=True, name=f"bms-record-{sid}")
            self._thread.start()
            return dict(self._state)

    def stop(self) -> dict:
        """Ask the session to finish early. The thread closes it out."""
        self._stop.set()
        return self.status()

    def _run(self, store, fetch, sid, samples, interval_s):
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


#: Process-global recorder — one aGate, one session at a time.
_recorder = Recorder()


def get_recorder() -> Recorder:
    return _recorder
