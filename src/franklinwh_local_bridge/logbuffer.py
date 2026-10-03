"""In-memory ring-buffer log handler + a DURABLE JSONL mirror for the Logs tab (P6).

A ``logging.Handler`` keeps the most-recent formatted records in a bounded
``collections.deque`` so ``GET /api/logs`` can serve them with no DB. To survive restarts
(the in-memory buffer alone resets every time the bridge starts), each record is also
appended to a bounded JSONL file under ``DATA_DIR`` and the buffer is **hydrated from that
file on startup** — so the Logs tab shows real history, not just the current boot.

Thread-safe by construction: ``deque.append`` / ``list(deque)`` are atomic under the GIL,
and the deque is bounded. File writes are best-effort and never raise (logging must not).
"""

from __future__ import annotations

import json
import logging
import os
from collections import deque

from . import environment

# Durable mirror: up to this many lines are kept on disk (rewritten when exceeded), so
# history persists across restarts without growing without bound.
_MAX_PERSIST = 5000

# Bounded shared buffer — newest on the right, oldest fall off the left. Sized to MATCH
# the on-disk mirror: previously the buffer was 500 while the file kept 5000, so the
# Logs tab could only ever see the newest 500 and the rest of the persisted history was
# unreachable. 5000 small dicts is a few MB — cheap, and this bridge logs only startup /
# state-changes / errors (never routine polls), so the buffer rarely fills.
_BUFFER: "deque[dict]" = deque(maxlen=_MAX_PERSIST)
_PERSIST_NAME = "logs.jsonl"
_write_count = 0
# Injected metrics store (SQLite). When set, log lines go to the DB (durable,
# queryable, paginated) instead of the rewritten JSONL file. See set_store().
_STORE = None

# Level-name → numeric level, covering both python names and the HA add-on level names
# (trace / notice / fatal). Used for the optional ``?level=`` minimum-level filter.
_LEVELS = {
    "trace": 5, "debug": 10, "info": 20, "notice": 25, "warning": 30,
    "warn": 30, "error": 40, "fatal": 50, "critical": 50,
}


def _persist_path() -> str:
    """DATA_DIR/logs.jsonl (read DATA_DIR dynamically so tests can redirect it)."""
    return os.path.join(environment.DATA_DIR, _PERSIST_NAME)


def _append_persist(entry: dict) -> None:
    """Append one entry as a JSON line; periodically trim. Never raises."""
    global _write_count
    try:
        with open(_persist_path(), "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, separators=(",", ":")) + "\n")
        _write_count += 1
        if _write_count % 500 == 0:
            _trim_persist()
    except Exception:  # noqa: BLE001 — persistence is best-effort
        pass


def _trim_persist() -> None:
    """Rewrite the file to its last ``_MAX_PERSIST`` lines when it grows past that."""
    try:
        path = _persist_path()
        if not os.path.exists(path):
            return
        with open(path, encoding="utf-8") as fh:
            lines = fh.readlines()
        if len(lines) > _MAX_PERSIST:
            with open(path, "w", encoding="utf-8") as fh:
                fh.writelines(lines[-_MAX_PERSIST:])
    except Exception:  # noqa: BLE001
        pass


def _hydrate_from_disk() -> None:
    """Load the tail of the persisted file into the buffer so history shows immediately
    after a restart. Oldest-first in the file → the bounded deque keeps the newest."""
    try:
        path = _persist_path()
        if not os.path.exists(path):
            return
        with open(path, encoding="utf-8") as fh:
            lines = fh.readlines()[-_BUFFER.maxlen:]
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                _BUFFER.append(json.loads(line))
            except Exception:  # noqa: BLE001 — skip a corrupt line
                pass
    except Exception:  # noqa: BLE001
        pass


class RingBufferHandler(logging.Handler):
    """Append each emitted record to the shared deque AND the durable JSONL mirror as a
    plain dict ``{ts, level, name, message}`` (``ts`` = epoch seconds). Never raises."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
        except Exception:  # noqa: BLE001 — logging must never raise
            try:
                msg = record.getMessage()
            except Exception:  # noqa: BLE001
                msg = "<unformattable log record>"
        entry = {
            "ts": record.created,
            "level": record.levelname,
            "name": record.name,
            "message": msg,
        }
        _BUFFER.append(entry)
        st = _STORE
        if st is not None:
            st.log_line(entry["ts"], entry["level"],
                        _LEVELS.get(str(entry["level"]).lower(), 0),
                        entry["name"], entry["message"])
        else:
            _append_persist(entry)   # fallback only when no DB store is attached


_installed = False


def install(logger_name: str = "franklinwh_local_bridge",
            level: int = logging.INFO) -> None:
    """Attach a single ``RingBufferHandler`` to ``logger_name`` (idempotent), hydrating the
    buffer from the persisted file first. Lowers the logger's own level to ``level`` when it
    would otherwise drop INFO records, so the buffer captures INFO+ regardless of the root
    level. Children propagate up to it."""
    global _installed
    logger = logging.getLogger(logger_name)
    if logger.level == logging.NOTSET or logger.level > level:
        logger.setLevel(level)
    if _installed:
        return
    _hydrate_from_disk()   # show prior-run history immediately
    _trim_persist()        # cap the file at startup
    handler = RingBufferHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    _installed = True


def get_logs(limit: int = 200, level: str | None = None,
             since: float | None = None) -> list[dict]:
    """The most-recent buffered entries, newest-first. ``level`` (optional) is a minimum
    level name — entries below it are filtered out. ``since`` (optional, epoch seconds)
    keeps only entries at or after that time. ``limit`` caps the count. Never raises."""
    try:
        entries = list(_BUFFER)
    except Exception:  # noqa: BLE001
        return []
    if since is not None:
        entries = [e for e in entries if float(e.get("ts", 0) or 0) >= since]
    min_lvl = _LEVELS.get((level or "").strip().lower()) if level else None
    if min_lvl is not None:
        entries = [e for e in entries
                   if _LEVELS.get(str(e.get("level", "")).lower(), 0) >= min_lvl]
    entries.reverse()  # newest-first
    if limit is not None and limit > 0:
        entries = entries[:limit]
    return entries


def clear() -> None:
    """Empty the in-memory buffer and, if a store is attached, its log rows — used by tests
    to isolate runs. NEVER touches a file: the old file-truncation here is exactly what let a
    non-isolated test wipe the live bridge's log (logs now live in the DB)."""
    global _write_count
    _BUFFER.clear()
    _write_count = 0
    st = _STORE
    if st is not None:
        try:
            st.clear_logs()
        except Exception:  # noqa: BLE001
            pass


def set_store(store) -> None:
    """Attach the SQLite metrics store so log lines persist to the DB (durable, queryable,
    paginated) rather than the legacy JSONL file. Call once after the store is created."""
    global _STORE
    _STORE = store


def hydrate_from_store(limit: int | None = None) -> None:
    """Refill the in-memory buffer from the DB (newest rows) so the Logs tab shows history
    immediately after a restart. Replaces the disk-file hydration when a store is present."""
    st = _STORE
    if st is None:
        return
    try:
        rows = st.logs(limit=limit or _BUFFER.maxlen)   # newest-first
        _BUFFER.clear()
        for e in reversed(rows):                         # oldest-first into the deque
            _BUFFER.append({"ts": e.get("ts"), "level": e.get("level"),
                            "name": e.get("name"), "message": e.get("message")})
    except Exception:  # noqa: BLE001
        pass


def import_jsonl_once() -> int:
    """One-time migration: import the legacy DATA_DIR/logs.jsonl into the DB, then rename it
    so it is never read (or clobbered) again. Returns the number of rows imported."""
    st = _STORE
    if st is None:
        return 0
    path = _persist_path()
    if not os.path.exists(path):
        return 0
    try:
        entries = []
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                    e["level_no"] = _LEVELS.get(str(e.get("level", "")).lower(), 0)
                    entries.append(e)
                except Exception:  # noqa: BLE001
                    pass
        n = st.log_bulk(entries)
        os.replace(path, path + ".migrated")   # keep a copy, but out of the read path
        return n
    except Exception:  # noqa: BLE001
        return 0
