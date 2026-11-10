"""Scheduler debug monitor (#345): why each schedule is, or is not, running.

After every tick, one line per enabled schedule per gateway goes into an in-memory ring.
It holds the last ``MAX_LINES`` lines and is lost on restart — never written to the
database, because it is a live view, not a record (the Activity Log is the record).

Every line is derived from what the tick already decided and the snapshot it already
built, so the monitor adds no reads of the aGate. Nothing here may raise into a tick.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any

MAX_LINES = 500

#: idle · blocked · holding · ready · running · skipped · deferred · retrying · done
STATES = ("idle", "blocked", "holding", "ready", "running", "skipped", "deferred",
          "retrying", "done")

_lines: deque = deque(maxlen=MAX_LINES)
_lock = threading.Lock()
_seq = 0


def _trace(nodes: list, snapshot: dict, match: str, kind: str) -> list[dict]:
    """Each condition leaf with its live value and result, from the tick's snapshot."""
    from . import scheduler
    if not nodes:
        return []
    trace: list[dict] = []
    scheduler.evaluate(nodes, snapshot, match or "all", trace)
    return [{"kind": kind, "sensor": r.get("sensor"), "op": r.get("op"),
             "value": r.get("value_sensor") if r.get("value_kind") == "sensor"
             else r.get("value"),
             "value2": r.get("value2"), "live_value": r.get("live_value"),
             "result": bool(r.get("result"))} for r in trace]


def record(*, gateway_id: str | None, entry: dict, state: str, detail: str,
           snapshot: dict, now: float | None = None) -> None:
    """Append one line. Never raises."""
    global _seq
    try:
        conds = (_trace(entry.get("conditions") or [], snapshot,
                        entry.get("match", "all"), "entry")
                 + _trace(entry.get("exit_conditions") or [], snapshot,
                          entry.get("exit_match", "all"), "exit"))
        with _lock:
            _seq += 1
            _lines.append({"seq": _seq, "ts": now if now is not None else time.time(),
                           "entry_id": entry.get("id"), "name": entry.get("name") or "",
                           "target": gateway_id or "", "state": state,
                           "detail": detail or "", "conditions": conds})
    except Exception:  # noqa: BLE001 — observing must never break a tick
        pass


def lines(*, entry_id: str | None = None, since: int = 0) -> list[dict]:
    """Lines newer than ``since``, oldest first, optionally for one schedule."""
    with _lock:
        out = [ln for ln in _lines if ln["seq"] > since]
    if entry_id:
        out = [ln for ln in out if ln["entry_id"] == entry_id]
    return out


def last_seq() -> int:
    """The newest line's number. Lower than a client's ``since`` after a restart."""
    with _lock:
        return _seq


def clear() -> None:
    """Empty the ring (tests). The UI's Clear only empties its own view."""
    global _seq
    with _lock:
        _lines.clear()
        _seq = 0
