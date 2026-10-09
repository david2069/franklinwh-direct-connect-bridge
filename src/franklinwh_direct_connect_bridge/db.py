"""Local time-series metrics store (stdlib sqlite3, WAL). No new dependency.

The poller writes one row per successful aGate poll; the REST layer reads it back
(raw or time-bucketed averages) for the Dashboard "Power History" chart. A single
process-global instance is shared by the poller thread and the REST threadpool, so
all access is serialised behind one lock. A DB failure must never corrupt the file
nor kill the poll loop — writes commit atomically and errors propagate to the
caller's guard.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

from .config import Settings, metrics_active

# Numeric columns written per sample (mode is stored separately as TEXT).
_NUM_COLS = ("soc", "grid_w", "solar_w", "battery_w", "load_w", "generator_w")

#: Tariff-tier accumulator arrays carried by cmdType 1301, stored as one JSON
#: column. These are RUNNING daily totals that reset at midnight, so which one
#: grew between two samples reveals the tier the device considered active — the
#: only way to observe when the tariff boundary moves. The gateway itself keeps
#: only end-of-day totals, so a day not recorded here is lost permanently.
#: See franklinwh_local.energy.tier_transitions() and BACKLOG DEF-1303-TIER-BASIS.
_TIER_KEYS = ("sharp", "peak", "flat", "valley")


class MetricsStore:
    """SQLite-backed rolling history of power samples."""

    def __init__(self, path: str) -> None:
        self.path = path
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS metrics(
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   ts INTEGER NOT NULL,
                   soc REAL, grid_w REAL, solar_w REAL, battery_w REAL,
                   load_w REAL, generator_w REAL, mode TEXT)"""
        )
        self._conn.execute("CREATE INDEX IF NOT EXISTS ix_metrics_ts ON metrics(ts)")
        self._migrate_gateway_id()
        self._migrate_tiers()
        self._migrate_bms()
        self._migrate_ha_instances()
        self._migrate_notify_devices()
        self._migrate_schedules()
        self._migrate_ha_exposed()
        self._migrate_schedule_log()
        self._migrate_occurrences()
        self._migrate_control_log()
        self._migrate_app_logs()
        self._migrate_disclaimer_acks()
        self._migrate_version_history()
        self._migrate_notify_log()
        self._migrate_billing_periods()
        self._migrate_cloud_pop()
        self._migrate_gateways()
        self._migrate_sites()
        self._migrate_meters()
        self._migrate_gateway_meter()
        self._migrate_utilities()
        self._migrate_tariffs()
        self._migrate_dispatches()
        self._migrate_app_config()
        self._migrate_tariff_dates()
        self._migrate_service_details()
        self._conn.commit()

    def _migrate_gateway_id(self) -> None:
        """Add the ``gateway_id`` column + index if this is a pre-multi-gateway DB.

        Existing rows keep NULL gateway_id (queried as the implicit single gateway).
        Idempotent — a no-op once the column exists.
        """
        cols = [r[1] for r in self._conn.execute("PRAGMA table_info(metrics)")]
        if "gateway_id" not in cols:
            self._conn.execute("ALTER TABLE metrics ADD COLUMN gateway_id TEXT")
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS ix_metrics_gw ON metrics(gateway_id, ts)")

    def _migrate_tiers(self) -> None:
        """Add the ``tiers`` column if this is a pre-tier DB. Idempotent."""
        cols = [r[1] for r in self._conn.execute("PRAGMA table_info(metrics)")]
        if "tiers" not in cols:
            self._conn.execute("ALTER TABLE metrics ADD COLUMN tiers TEXT")

    def insert(self, state: dict, ts: int, gateway_id: str | None = None,
               tiers: dict | None = None) -> None:
        """Insert one sample. Missing keys → NULL. Under lock; commits atomically.

        ``tiers`` is the 1301 tariff-tier accumulator block; stored as JSON when
        present, NULL otherwise. Malformed input is stored as NULL rather than
        raising — a poll must never die over a telemetry extra.
        """
        vals = [ts]
        vals += [_num(state.get(k)) for k in _NUM_COLS]
        vals.append(state.get("mode"))
        vals.append(gateway_id)
        vals.append(_tiers_json(tiers))
        with self._lock:
            self._conn.execute(
                "INSERT INTO metrics(ts, soc, grid_w, solar_w, battery_w, load_w, "
                "generator_w, mode, gateway_id, tiers) VALUES (?,?,?,?,?,?,?,?,?,?)",
                vals,
            )
            self._conn.commit()

    def tier_samples(self, start: int, end: int,
                     gateway: str | None = None) -> list[dict]:
        """Samples that carry tier accumulators, oldest first.

        Returns ``[{"ts": int, **tier_arrays}]`` — the shape
        ``franklinwh_local.energy.tier_transitions()`` expects, so the active-tier
        boundary can be extracted directly from stored history.
        """
        sql = ("SELECT ts, tiers FROM metrics WHERE ts BETWEEN ? AND ? "
               "AND tiers IS NOT NULL")
        args: list = [start, end]
        if gateway is not None:
            sql += " AND gateway_id = ?"
            args.append(gateway)
        with self._lock:
            rows = self._conn.execute(sql + " ORDER BY ts", args).fetchall()
        out = []
        for ts, blob in rows:
            try:
                parsed = json.loads(blob)
            except (TypeError, ValueError):
                continue
            if isinstance(parsed, dict):
                out.append({"ts": int(ts), **parsed})
        return out

    def query(self, start: int, end: int, bucket_s: int | None,
              gateway: str | None = None) -> list[dict]:
        """Return samples between ``start`` and ``end`` (inclusive).

        With a positive ``bucket_s`` the rows are grouped into fixed time buckets and
        the numeric columns averaged (mode is dropped — it doesn't average). Otherwise
        raw rows are returned (mode included). When ``gateway`` is given, only that
        gateway's rows are returned. All numerics are None-safe and rounded
        (soc → 1dp, watts → 0dp).
        """
        gw_sql = " AND gateway_id = :gw" if gateway is not None else ""
        if bucket_s and bucket_s > 0:
            params = {"b": bucket_s, "s": start, "e": end}
            if gateway is not None:
                params["gw"] = gateway
            with self._lock:
                rows = self._conn.execute(
                    "SELECT (ts/:b)*:b AS bts, AVG(soc), AVG(grid_w), AVG(solar_w), "
                    "AVG(battery_w), AVG(load_w), AVG(generator_w) "
                    "FROM metrics WHERE ts BETWEEN :s AND :e" + gw_sql +
                    " GROUP BY bts ORDER BY bts",
                    params,
                ).fetchall()
            return [
                {
                    "ts": int(r[0]),
                    "soc": _round(r[1], 1),
                    "grid_w": _round(r[2], 0),
                    "solar_w": _round(r[3], 0),
                    "battery_w": _round(r[4], 0),
                    "load_w": _round(r[5], 0),
                    "generator_w": _round(r[6], 0),
                }
                for r in rows
            ]
        params = {"s": start, "e": end}
        if gateway is not None:
            params["gw"] = gateway
        with self._lock:
            rows = self._conn.execute(
                "SELECT ts, soc, grid_w, solar_w, battery_w, load_w, generator_w, mode "
                "FROM metrics WHERE ts BETWEEN :s AND :e" + gw_sql + " ORDER BY ts",
                params,
            ).fetchall()
        return [
            {
                "ts": int(r[0]),
                "soc": _round(r[1], 1),
                "grid_w": _round(r[2], 0),
                "solar_w": _round(r[3], 0),
                "battery_w": _round(r[4], 0),
                "load_w": _round(r[5], 0),
                "generator_w": _round(r[6], 0),
                "mode": r[7],
            }
            for r in rows
        ]

    def mode_segments(self, start: int, end: int, gateway: str | None = None,
                      bucket_s: int = 600) -> list[dict]:
        """Coalesced work-mode runs over [start, end] for the timeline's mode band.

        The gateway's reported mode flaps between reads (Self/TOU can alternate every
        poll), so raw runs would be thousands of slivers. Instead, tally the mode per
        ``bucket_s`` window, take the dominant one, then coalesce consecutive buckets —
        a clean band that reflects the prevailing mode, not the jitter."""
        from collections import Counter
        q = "SELECT ts, mode FROM metrics WHERE ts>=? AND ts<=?"
        args: list = [start, end]
        if gateway:
            q += " AND gateway_id=?"; args.append(gateway)
        q += " ORDER BY ts"
        buckets: dict[int, Counter] = {}
        for ts, mode in self._conn.execute(q, args).fetchall():
            if mode is None:
                continue
            buckets.setdefault((int(ts) - start) // bucket_s, Counter())[mode] += 1
        segs: list[dict] = []
        for bi in sorted(buckets):
            mode = buckets[bi].most_common(1)[0][0]
            b_start = start + bi * bucket_s
            b_end = min(end, b_start + bucket_s)
            if segs and segs[-1]["mode"] == mode and b_start - segs[-1]["end"] <= bucket_s:
                segs[-1]["end"] = b_end
            else:
                segs.append({"start": b_start, "end": b_end, "mode": mode})
        return segs

    # ── BMS recording sessions ──────────────────────────────────────────
    # A session is a bounded burst of full 1705 snapshots (all 16 cell voltages +
    # temperatures), recorded on demand for trend analysis. Deliberately separate
    # from `metrics`: that table is one wide row per 30s forever, whereas these are
    # dense per-cell arrays kept only for the sessions the user chose to record.

    def _migrate_bms(self) -> None:
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS bms_sessions(
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   started_ts INTEGER NOT NULL,
                   ended_ts INTEGER,
                   gateway_id TEXT, apower_sn TEXT, dev_id INTEGER,
                   interval_s REAL, planned INTEGER, label TEXT)"""
        )
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS bms_samples(
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   session_id INTEGER NOT NULL,
                   ts INTEGER NOT NULL,
                   soc REAL, soh REAL, pack_v REAL, current_a REAL,
                   volts TEXT, temps TEXT)"""
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS ix_bms_samples ON bms_samples(session_id, ts)")

    # ── Home Assistant instances ─────────────────────────────────────────────
    # One bridge, many Home Assistants. Replaces the single HA_URL/HA_TOKEN pair,
    # which could only ever describe one. Tokens are stored here and NEVER echoed
    # back to a client — the API reports only whether one is set.
    def _migrate_ha_instances(self) -> None:
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS ha_instances(
                   id TEXT PRIMARY KEY,
                   name TEXT NOT NULL,
                   base_url TEXT NOT NULL,
                   token TEXT,
                   is_default INTEGER NOT NULL DEFAULT 0,
                   enabled INTEGER NOT NULL DEFAULT 1,
                   created_at REAL NOT NULL DEFAULT 0,
                   updated_at REAL NOT NULL DEFAULT 0)"""
        )
        self._conn.commit()

    def _ha_rows(self, cur) -> list[dict]:
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    def ha_instances(self) -> list[dict]:
        with self._lock:
            return self._ha_rows(self._conn.execute(
                "SELECT * FROM ha_instances ORDER BY is_default DESC, name"))

    def ha_instance(self, ha_id: str) -> dict | None:
        with self._lock:
            rows = self._ha_rows(self._conn.execute(
                "SELECT * FROM ha_instances WHERE id=?", (ha_id,)))
        return rows[0] if rows else None

    def create_ha_instance(self, *, ha_id: str, name: str, base_url: str,
                           token: str | None = None, is_default: bool = False,
                           enabled: bool = True, now: float | None = None) -> dict:
        ts = float(now if now is not None else time.time())
        with self._lock:
            if is_default:
                self._conn.execute("UPDATE ha_instances SET is_default=0")
            self._conn.execute(
                "INSERT INTO ha_instances(id,name,base_url,token,is_default,enabled,"
                "created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)",
                (ha_id, name, base_url, token, int(is_default), int(enabled), ts, ts))
            self._conn.commit()
        return self.ha_instance(ha_id)

    def update_ha_instance(self, ha_id: str, **fields) -> dict | None:
        allowed = {"name", "base_url", "token", "is_default", "enabled"}
        sets = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if not sets:
            return self.ha_instance(ha_id)
        with self._lock:
            if sets.get("is_default"):
                self._conn.execute("UPDATE ha_instances SET is_default=0")
            for k in ("is_default", "enabled"):
                if k in sets:
                    sets[k] = int(bool(sets[k]))
            cols = ", ".join(f"{k}=?" for k in sets)
            self._conn.execute(
                f"UPDATE ha_instances SET {cols}, updated_at=? WHERE id=?",
                (*sets.values(), time.time(), ha_id))
            self._conn.commit()
        return self.ha_instance(ha_id)

    def delete_ha_instance(self, ha_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute("DELETE FROM ha_instances WHERE id=?", (ha_id,))
            self._conn.commit()
            return cur.rowcount > 0

    # ── gateways (DB-backed roster) ──────────────────────────────────────────
    def _migrate_gateways(self) -> None:
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS gateways(
                   id TEXT PRIMARY KEY,
                   label TEXT NOT NULL,
                   host TEXT NOT NULL DEFAULT '',
                   port INTEGER NOT NULL DEFAULT 9000,
                   is_default INTEGER NOT NULL DEFAULT 0,
                   enabled INTEGER NOT NULL DEFAULT 1,
                   is_mock INTEGER NOT NULL DEFAULT 0,
                   mock_seed INTEGER,
                   mock_units INTEGER NOT NULL DEFAULT 1,
                   publish_ha INTEGER NOT NULL DEFAULT 1,
                   description TEXT NOT NULL DEFAULT '',
                   created_at REAL NOT NULL DEFAULT 0,
                   updated_at REAL NOT NULL DEFAULT 0)""")
        self._conn.commit()

    def gateways(self) -> list[dict]:
        with self._lock:
            return self._ha_rows(self._conn.execute(
                "SELECT * FROM gateways ORDER BY is_default DESC, label"))

    def gateway(self, gw_id: str) -> dict | None:
        with self._lock:
            rows = self._ha_rows(self._conn.execute(
                "SELECT * FROM gateways WHERE id=?", (gw_id,)))
        return rows[0] if rows else None

    def create_gateway(self, *, gw_id: str, label: str, host: str = "", port: int = 9000,
                       is_default: bool = False, enabled: bool = True, is_mock: bool = False,
                       mock_seed: int | None = None, mock_units: int = 1,
                       publish_ha: bool = True, description: str = "",
                       now: float | None = None) -> dict:
        ts = float(now if now is not None else time.time())
        with self._lock:
            if is_default:
                self._conn.execute("UPDATE gateways SET is_default=0")
            self._conn.execute(
                "INSERT INTO gateways(id,label,host,port,is_default,enabled,is_mock,"
                "mock_seed,mock_units,publish_ha,description,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (gw_id, label, host, int(port), int(is_default), int(enabled), int(is_mock),
                 mock_seed, int(mock_units), int(publish_ha), description, ts, ts))
            self._conn.commit()
        return self.gateway(gw_id)

    def update_gateway(self, gw_id: str, **fields) -> dict | None:
        allowed = {"label", "host", "port", "is_default", "enabled", "is_mock",
                   "mock_seed", "mock_units", "publish_ha", "description", "meter_id"}
        sets = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if not sets:
            return self.gateway(gw_id)
        with self._lock:
            if sets.get("is_default"):
                self._conn.execute("UPDATE gateways SET is_default=0")
            for k in ("is_default", "enabled", "is_mock", "publish_ha"):
                if k in sets:
                    sets[k] = int(bool(sets[k]))
            for k in ("port", "mock_units"):
                if k in sets:
                    sets[k] = int(sets[k])
            cols = ", ".join(f"{k}=?" for k in sets)
            self._conn.execute(
                f"UPDATE gateways SET {cols}, updated_at=? WHERE id=?",
                (*sets.values(), time.time(), gw_id))
            self._conn.commit()
        return self.gateway(gw_id)

    def delete_gateway(self, gw_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute("DELETE FROM gateways WHERE id=?", (gw_id,))
            self._conn.commit()
            return cur.rowcount > 0

    def seed_gateways(self, entries: list[tuple[str, str]]) -> int:
        """First-boot migration: if the roster table is empty, insert one row per
        ``(host, label)`` from the env config so existing installs get exactly their
        current gateways (first = default). No-op once any row exists. Returns rows added."""
        import uuid as _uuid
        with self._lock:
            n = self._conn.execute("SELECT COUNT(*) FROM gateways").fetchone()[0]
        if n or not entries:
            return 0
        added = 0
        for i, (host, label) in enumerate(entries):
            self.create_gateway(gw_id=_uuid.uuid4().hex[:12], label=label or host,
                                host=host, is_default=(i == 0), enabled=True)
            added += 1
        return added

    # ── sites + meters (multi-site / multi-meter model) ───────────────────────
    def _migrate_sites(self) -> None:
        """A physical installation grouping meters + gateways. Multi-row (a step beyond
        the Modbus bridge's singleton) so a fleet can run several; single-site installs
        get one default 'Home' site."""
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS sites(
                   id TEXT PRIMARY KEY,
                   name TEXT NOT NULL DEFAULT 'Home',
                   timezone TEXT NOT NULL DEFAULT '',
                   latitude REAL, longitude REAL, postcode TEXT NOT NULL DEFAULT '',
                   currency TEXT NOT NULL DEFAULT '', region TEXT NOT NULL DEFAULT '',
                   is_default INTEGER NOT NULL DEFAULT 0,
                   created_at REAL NOT NULL DEFAULT 0, updated_at REAL NOT NULL DEFAULT 0)""")
        self._conn.commit()

    def _migrate_meters(self) -> None:
        """The connection point: AC type + fixed rated amperage + meter number, belonging
        to one site, supplied by one utility, priced by 0..1 tariff (utility/tariff filled
        by the later Utility+Tariff feature)."""
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS meters(
                   id TEXT PRIMARY KEY,
                   site_id TEXT NOT NULL DEFAULT '',
                   utility_id TEXT, tariff_id TEXT,
                   name TEXT NOT NULL DEFAULT 'Meter 1',
                   meter_number TEXT NOT NULL DEFAULT '',
                   ac_type TEXT NOT NULL DEFAULT 'single',
                   rated_amps REAL,
                   pto_status TEXT NOT NULL DEFAULT 'unknown',
                   timezone TEXT NOT NULL DEFAULT '',
                   is_default INTEGER NOT NULL DEFAULT 0,
                   created_at REAL NOT NULL DEFAULT 0, updated_at REAL NOT NULL DEFAULT 0)""")
        self._conn.commit()

    def _migrate_gateway_meter(self) -> None:
        """Gateway → Meter link (a gateway connects to exactly one meter; its site is
        derived via the meter). Additive column on the existing gateways table."""
        cols = [r[1] for r in self._conn.execute("PRAGMA table_info(gateways)").fetchall()]
        if "meter_id" not in cols:
            self._conn.execute("ALTER TABLE gateways ADD COLUMN meter_id TEXT")
        self._conn.commit()

    def sites(self) -> list[dict]:
        with self._lock:
            return self._ha_rows(self._conn.execute(
                "SELECT * FROM sites ORDER BY is_default DESC, name"))

    def site(self, sid: str) -> dict | None:
        with self._lock:
            rows = self._ha_rows(self._conn.execute("SELECT * FROM sites WHERE id=?", (sid,)))
        return rows[0] if rows else None

    def create_site(self, *, sid: str, name: str, timezone: str = "", latitude=None,
                    longitude=None, postcode: str = "", currency: str = "", region: str = "",
                    is_default: bool = False, now: float | None = None) -> dict:
        ts = float(now if now is not None else time.time())
        with self._lock:
            if is_default:
                self._conn.execute("UPDATE sites SET is_default=0")
            self._conn.execute(
                "INSERT INTO sites(id,name,timezone,latitude,longitude,postcode,currency,"
                "region,is_default,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (sid, name, timezone, latitude, longitude, postcode, currency, region,
                 int(is_default), ts, ts))
            self._conn.commit()
        return self.site(sid)

    def update_site(self, sid: str, **fields) -> dict | None:
        allowed = {"name", "timezone", "latitude", "longitude", "postcode", "currency",
                   "region", "is_default"}
        sets = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if not sets:
            return self.site(sid)
        with self._lock:
            if sets.get("is_default"):
                self._conn.execute("UPDATE sites SET is_default=0")
            if "is_default" in sets:
                sets["is_default"] = int(bool(sets["is_default"]))
            cols = ", ".join(f"{k}=?" for k in sets)
            self._conn.execute(f"UPDATE sites SET {cols}, updated_at=? WHERE id=?",
                               (*sets.values(), time.time(), sid))
            self._conn.commit()
        return self.site(sid)

    def delete_site(self, sid: str) -> bool:
        with self._lock:
            cur = self._conn.execute("DELETE FROM sites WHERE id=?", (sid,))
            self._conn.commit()
            return cur.rowcount > 0

    def meters(self, *, site_id: str | None = None) -> list[dict]:
        q = "SELECT * FROM meters"; args: list = []
        if site_id is not None:
            q += " WHERE site_id=?"; args.append(site_id)
        q += " ORDER BY is_default DESC, name"
        with self._lock:
            return self._ha_rows(self._conn.execute(q, args))

    def meter(self, mid: str) -> dict | None:
        with self._lock:
            rows = self._ha_rows(self._conn.execute("SELECT * FROM meters WHERE id=?", (mid,)))
        return rows[0] if rows else None

    def create_meter(self, *, mid: str, site_id: str, name: str = "Meter 1",
                     meter_number: str = "", ac_type: str = "single", rated_amps=None,
                     utility_id=None, tariff_id=None, pto_status: str = "unknown",
                     pto_reference: str = "", timezone: str = "", is_default: bool = False,
                     now: float | None = None) -> dict:
        ts = float(now if now is not None else time.time())
        with self._lock:
            if is_default:
                self._conn.execute("UPDATE meters SET is_default=0 WHERE site_id=?", (site_id,))
            self._conn.execute(
                "INSERT INTO meters(id,site_id,utility_id,tariff_id,name,meter_number,ac_type,"
                "rated_amps,pto_status,pto_reference,timezone,is_default,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (mid, site_id, utility_id, tariff_id, name, meter_number, ac_type, rated_amps,
                 pto_status, pto_reference, timezone, int(is_default), ts, ts))
            self._conn.commit()
        return self.meter(mid)

    def update_meter(self, mid: str, **fields) -> dict | None:
        allowed = {"site_id", "utility_id", "tariff_id", "name", "meter_number", "ac_type",
                   "rated_amps", "pto_status", "pto_reference", "timezone", "is_default"}
        sets = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if not sets:
            return self.meter(mid)
        with self._lock:
            if sets.get("is_default"):
                row = self.meter(mid)
                self._conn.execute("UPDATE meters SET is_default=0 WHERE site_id=?",
                                   (sets.get("site_id") or (row or {}).get("site_id") or "",))
            if "is_default" in sets:
                sets["is_default"] = int(bool(sets["is_default"]))
            cols = ", ".join(f"{k}=?" for k in sets)
            self._conn.execute(f"UPDATE meters SET {cols}, updated_at=? WHERE id=?",
                               (*sets.values(), time.time(), mid))
            self._conn.commit()
        return self.meter(mid)

    def delete_meter(self, mid: str) -> bool:
        with self._lock:
            cur = self._conn.execute("DELETE FROM meters WHERE id=?", (mid,))
            self._conn.commit()
            return cur.rowcount > 0

    def ensure_default_site_meter(self) -> dict:
        """First-boot: guarantee one default Site + Meter and attach any unassigned gateway
        to the default meter. Idempotent; single-site installs never see the difference."""
        import uuid as _uuid
        made = {"site": False, "meter": False, "attached": 0}
        with self._lock:
            n_sites = self._conn.execute("SELECT COUNT(*) FROM sites").fetchone()[0]
            n_meters = self._conn.execute("SELECT COUNT(*) FROM meters").fetchone()[0]
        if not n_sites:
            self.create_site(sid="site_" + _uuid.uuid4().hex[:8], name="Home", is_default=True)
            made["site"] = True
        default_site = next((s for s in self.sites() if s.get("is_default")), (self.sites() or [None])[0])
        if not n_meters and default_site:
            self.create_meter(mid="meter_" + _uuid.uuid4().hex[:8], site_id=default_site["id"],
                              name="Meter 1", is_default=True)
            made["meter"] = True
        default_meter = None
        if default_site:
            ms = self.meters(site_id=default_site["id"])
            default_meter = next((m for m in ms if m.get("is_default")), (ms or [None])[0])
        if default_meter:
            with self._lock:
                cur = self._conn.execute(
                    "UPDATE gateways SET meter_id=? WHERE meter_id IS NULL OR meter_id=''",
                    (default_meter["id"],))
                self._conn.commit()
                made["attached"] = cur.rowcount
        return made

    # ── utilities + tariffs (the supplier + its rate plans) ───────────────────
    _TARIFF_JSON = ("pricing", "demand_window", "bonus_window", "charge_window", "fixed_charges")

    def _migrate_utilities(self) -> None:
        """The electricity supplier: retailer + network/DNSP + the plan-level export/charge
        permissions. A meter is supplied by one utility; a utility offers many tariffs."""
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS utilities(
                   id TEXT PRIMARY KEY,
                   name TEXT NOT NULL DEFAULT '',
                   network_dnsp TEXT NOT NULL DEFAULT '',
                   country TEXT NOT NULL DEFAULT '',
                   plan_type TEXT NOT NULL DEFAULT 'unknown',
                   export_allowed INTEGER NOT NULL DEFAULT 1,
                   solar_export_allowed INTEGER NOT NULL DEFAULT 1,
                   battery_export_allowed INTEGER NOT NULL DEFAULT 1,
                   export_limit_kw REAL,
                   charging_allowed INTEGER NOT NULL DEFAULT 1,
                   discharging_allowed INTEGER NOT NULL DEFAULT 1,
                   created_at REAL NOT NULL DEFAULT 0, updated_at REAL NOT NULL DEFAULT 0)""")
        self._conn.commit()

    def _migrate_tariffs(self) -> None:
        """A rate plan under a utility: the seasonal-TOU/tiered rate model (`pricing`), the
        demand/bonus/export-charge windows, fixed charges, and the billing-cycle day."""
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS tariffs(
                   id TEXT PRIMARY KEY,
                   utility_id TEXT NOT NULL DEFAULT '',
                   name TEXT NOT NULL DEFAULT '',
                   pricing TEXT, demand_window TEXT, bonus_window TEXT, charge_window TEXT,
                   fixed_charges TEXT,
                   billing_cycle_day INTEGER NOT NULL DEFAULT 1,
                   plan_version TEXT NOT NULL DEFAULT '',
                   created_at REAL NOT NULL DEFAULT 0, updated_at REAL NOT NULL DEFAULT 0)""")
        self._conn.commit()

    def _decode_tariff(self, row: dict | None) -> dict | None:
        if row is None:
            return None
        import json as _json
        for k in self._TARIFF_JSON:
            v = row.get(k)
            if isinstance(v, str) and v:
                try:
                    row[k] = _json.loads(v)
                except Exception:  # noqa: BLE001
                    row[k] = None
            elif not v:
                row[k] = None
        return row

    def utilities(self) -> list[dict]:
        with self._lock:
            return self._ha_rows(self._conn.execute("SELECT * FROM utilities ORDER BY name"))

    def utility(self, uid: str) -> dict | None:
        with self._lock:
            rows = self._ha_rows(self._conn.execute("SELECT * FROM utilities WHERE id=?", (uid,)))
        return rows[0] if rows else None

    def create_utility(self, *, uid: str, name: str = "", now: float | None = None, **fields) -> dict:
        ts = float(now if now is not None else time.time())
        allowed = ("network_dnsp", "country", "plan_type", "export_allowed",
                   "solar_export_allowed", "battery_export_allowed", "export_limit_kw",
                   "charging_allowed", "discharging_allowed", "export_note", "effective_start", "effective_end")
        cols = ["id", "name", "created_at", "updated_at"] + [k for k in allowed if k in fields]
        vals = [uid, name, ts, ts] + [fields[k] for k in allowed if k in fields]
        with self._lock:
            self._conn.execute(
                f"INSERT INTO utilities({','.join(cols)}) VALUES ({','.join('?'*len(cols))})", vals)
            self._conn.commit()
        return self.utility(uid)

    def update_utility(self, uid: str, **fields) -> dict | None:
        allowed = {"name", "network_dnsp", "country", "plan_type", "export_allowed",
                   "solar_export_allowed", "battery_export_allowed", "export_limit_kw",
                   "charging_allowed", "discharging_allowed", "export_note", "effective_start", "effective_end"}
        sets = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if not sets:
            return self.utility(uid)
        for k in ("export_allowed", "solar_export_allowed", "battery_export_allowed",
                  "charging_allowed", "discharging_allowed"):
            if k in sets:
                sets[k] = int(bool(sets[k]))
        with self._lock:
            cols = ", ".join(f"{k}=?" for k in sets)
            self._conn.execute(f"UPDATE utilities SET {cols}, updated_at=? WHERE id=?",
                               (*sets.values(), time.time(), uid))
            self._conn.commit()
        return self.utility(uid)

    def delete_utility(self, uid: str) -> bool:
        with self._lock:
            cur = self._conn.execute("DELETE FROM utilities WHERE id=?", (uid,))
            self._conn.commit()
            return cur.rowcount > 0

    def tariffs(self, *, utility_id: str | None = None) -> list[dict]:
        q = "SELECT * FROM tariffs"; args: list = []
        if utility_id is not None:
            q += " WHERE utility_id=?"; args.append(utility_id)
        q += " ORDER BY name"
        with self._lock:
            rows = self._ha_rows(self._conn.execute(q, args))
        return [self._decode_tariff(r) for r in rows]

    def tariff(self, tid: str) -> dict | None:
        with self._lock:
            rows = self._ha_rows(self._conn.execute("SELECT * FROM tariffs WHERE id=?", (tid,)))
        return self._decode_tariff(rows[0]) if rows else None

    def create_tariff(self, *, tid: str, utility_id: str, name: str = "",
                      billing_cycle_day: int = 1, plan_version: str = "",
                      effective_start: str | None = None, effective_end: str | None = None,
                      now: float | None = None, **json_fields) -> dict:
        import json as _json
        ts = float(now if now is not None else time.time())
        j = {k: (_json.dumps(json_fields[k]) if json_fields.get(k) is not None else None)
             for k in self._TARIFF_JSON}
        with self._lock:
            self._conn.execute(
                "INSERT INTO tariffs(id,utility_id,name,pricing,demand_window,bonus_window,"
                "charge_window,fixed_charges,billing_cycle_day,plan_version,effective_start,"
                "effective_end,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (tid, utility_id, name, j["pricing"], j["demand_window"], j["bonus_window"],
                 j["charge_window"], j["fixed_charges"], int(billing_cycle_day), plan_version,
                 effective_start or None, effective_end or None, ts, ts))
            self._conn.commit()
        return self.tariff(tid)

    def update_tariff(self, tid: str, **fields) -> dict | None:
        import json as _json
        scalar = {"utility_id", "name", "billing_cycle_day", "plan_version", "effective_start", "effective_end"}
        sets: dict = {}
        for k, v in fields.items():
            if k in scalar and v is not None:
                sets[k] = int(v) if k == "billing_cycle_day" else v
            elif k in self._TARIFF_JSON and v is not None:
                sets[k] = _json.dumps(v)
        if not sets:
            return self.tariff(tid)
        with self._lock:
            cols = ", ".join(f"{k}=?" for k in sets)
            self._conn.execute(f"UPDATE tariffs SET {cols}, updated_at=? WHERE id=?",
                               (*sets.values(), time.time(), tid))
            self._conn.commit()
        return self.tariff(tid)

    def delete_tariff(self, tid: str) -> bool:
        with self._lock:
            cur = self._conn.execute("DELETE FROM tariffs WHERE id=?", (tid,))
            self._conn.commit()
            return cur.rowcount > 0

    # ── notification devices ─────────────────────────────────────────────────
    # A named target: alias + which HA instance + which notify.* service. Separate
    # from the instance itself because one HA exposes many targets (a phone, a
    # speaker, a persistent notification) and each needs its own on/off WITHOUT
    # being deleted — turning a device off for a week should not lose its config.
    def _migrate_notify_devices(self) -> None:
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS notify_devices(
                   id TEXT PRIMARY KEY,
                   alias TEXT NOT NULL,
                   instance_id TEXT NOT NULL,
                   service TEXT NOT NULL,
                   enabled INTEGER NOT NULL DEFAULT 1,
                   created_at REAL NOT NULL DEFAULT 0,
                   updated_at REAL NOT NULL DEFAULT 0)"""
        )
        self._conn.commit()

    def notify_devices(self) -> list[dict]:
        with self._lock:
            return self._ha_rows(self._conn.execute(
                "SELECT * FROM notify_devices ORDER BY alias"))

    def notify_device(self, dev_id: str) -> dict | None:
        with self._lock:
            rows = self._ha_rows(self._conn.execute(
                "SELECT * FROM notify_devices WHERE id=?", (dev_id,)))
        return rows[0] if rows else None

    def create_notify_device(self, *, dev_id: str, alias: str, instance_id: str,
                             service: str, enabled: bool = True,
                             now: float | None = None) -> dict:
        ts = float(now if now is not None else time.time())
        with self._lock:
            self._conn.execute(
                "INSERT INTO notify_devices(id,alias,instance_id,service,enabled,"
                "created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
                (dev_id, alias, instance_id, service, int(enabled), ts, ts))
            self._conn.commit()
        return self.notify_device(dev_id)

    def update_notify_device(self, dev_id: str, **fields) -> dict | None:
        allowed = {"alias", "instance_id", "service", "enabled"}
        sets = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if not sets:
            return self.notify_device(dev_id)
        if "enabled" in sets:
            sets["enabled"] = int(bool(sets["enabled"]))
        with self._lock:
            cols = ", ".join(f"{k}=?" for k in sets)
            self._conn.execute(
                f"UPDATE notify_devices SET {cols}, updated_at=? WHERE id=?",
                (*sets.values(), time.time(), dev_id))
            self._conn.commit()
        return self.notify_device(dev_id)

    def delete_notify_device(self, dev_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute("DELETE FROM notify_devices WHERE id=?", (dev_id,))
            self._conn.commit()
            return cur.rowcount > 0

    # ── schedules ────────────────────────────────────────────────────────────
    # `spec` holds the whole entry as JSON (trigger, action, conditions, HA
    # actions). Kept as one document rather than a dozen columns because the
    # shape is still moving; the columns here are only what queries need.
    def _migrate_schedules(self) -> None:
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS schedules(
                   id TEXT PRIMARY KEY,
                   name TEXT NOT NULL,
                   enabled INTEGER NOT NULL DEFAULT 1,
                   spec TEXT NOT NULL,
                   last_fired_ts REAL,
                   last_fired_day TEXT,
                   last_result TEXT,
                   created_at REAL NOT NULL DEFAULT 0,
                   updated_at REAL NOT NULL DEFAULT 0)"""
        )
        self._conn.commit()

    def _sched_row(self, r: dict) -> dict:
        out = dict(r)
        try:
            out.update(json.loads(out.pop("spec") or "{}"))
        except (ValueError, TypeError):
            out["spec_error"] = "stored spec is not valid JSON"
        out["enabled"] = bool(out.get("enabled"))
        return out

    def schedules(self) -> list[dict]:
        with self._lock:
            rows = self._ha_rows(self._conn.execute(
                "SELECT * FROM schedules ORDER BY name"))
        return [self._sched_row(r) for r in rows]

    def schedule(self, sid: str) -> dict | None:
        with self._lock:
            rows = self._ha_rows(self._conn.execute(
                "SELECT * FROM schedules WHERE id=?", (sid,)))
        return self._sched_row(rows[0]) if rows else None

    def create_schedule(self, *, sid: str, name: str, spec: dict,
                        enabled: bool = True, now: float | None = None) -> dict:
        ts = float(now if now is not None else time.time())
        with self._lock:
            self._conn.execute(
                "INSERT INTO schedules(id,name,enabled,spec,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?)",
                (sid, name, int(enabled), json.dumps(spec), ts, ts))
            self._conn.commit()
        return self.schedule(sid)

    def update_schedule(self, sid: str, *, name: str | None = None,
                        enabled: bool | None = None,
                        spec: dict | None = None) -> dict | None:
        sets: dict[str, Any] = {}
        if name is not None:
            sets["name"] = name
        if enabled is not None:
            sets["enabled"] = int(bool(enabled))
        if spec is not None:
            sets["spec"] = json.dumps(spec)
        if not sets:
            return self.schedule(sid)
        with self._lock:
            cols = ", ".join(f"{k}=?" for k in sets)
            self._conn.execute(
                f"UPDATE schedules SET {cols}, updated_at=? WHERE id=?",
                (*sets.values(), time.time(), sid))
            self._conn.commit()
        return self.schedule(sid)

    def delete_schedule(self, sid: str) -> bool:
        with self._lock:
            cur = self._conn.execute("DELETE FROM schedules WHERE id=?", (sid,))
            self._conn.commit()
            return cur.rowcount > 0

    def mark_schedule_fired(self, sid: str, day: str, result: str,
                            now: float | None = None) -> None:
        """Record the outcome — including a failure, so the UI can show WHY an
        entry did nothing rather than leaving the user to guess."""
        with self._lock:
            self._conn.execute(
                "UPDATE schedules SET last_fired_ts=?, last_fired_day=?, last_result=? "
                "WHERE id=?",
                (float(now if now is not None else time.time()), day, result, sid))
            self._conn.commit()

    # ── exposed HA entities ──────────────────────────────────────────────────
    # Which entities the user has marked visible/exposed. A HA can have thousands;
    # this is just the allowlist, keyed "<instance_id>:<entity_id>".
    def _migrate_ha_exposed(self) -> None:
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS ha_exposed(key TEXT PRIMARY KEY)")
        self._conn.commit()

    def ha_exposed_ids(self) -> set:
        with self._lock:
            return {r[0] for r in self._conn.execute("SELECT key FROM ha_exposed")}

    def set_ha_exposed(self, instance_id: str, entity_id: str, exposed: bool) -> None:
        key = f"{instance_id}:{entity_id}"
        with self._lock:
            if exposed:
                self._conn.execute(
                    "INSERT OR IGNORE INTO ha_exposed(key) VALUES (?)", (key,))
            else:
                self._conn.execute("DELETE FROM ha_exposed WHERE key=?", (key,))
            self._conn.commit()

    # ── schedule fire history ────────────────────────────────────────────────
    # Every fire (or skip, when run manually) is logged so a schedule that did
    # nothing can say why — the recurring complaint about schedulers.
    def _migrate_schedule_log(self) -> None:
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS schedule_log(
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   ts REAL NOT NULL,
                   schedule_id TEXT NOT NULL,
                   name TEXT,
                   status TEXT,
                   result TEXT)"""
        )
        # The stream was one undifferentiated list, and the measurement that forced
        # this split is worth keeping: execution was 2.2% of rows (9 of 405) while
        # `gated` alone was 76%. Under ONE 2000-row cap, routine chatter evicts the
        # errors long before they age out — the records that matter are the first to
        # go. `severity` gives each class its own budget.
        cols = [r[1] for r in self._conn.execute("PRAGMA table_info(schedule_log)")]
        if "severity" not in cols:
            self._conn.execute(
                "ALTER TABLE schedule_log ADD COLUMN severity TEXT NOT NULL DEFAULT 'event'")
            # Backfill: classify what is already there rather than calling it all 'event'.
            self._conn.execute(
                "UPDATE schedule_log SET severity='error' WHERE status IN "
                "('error','failed','missed')")
            self._conn.execute(
                "UPDATE schedule_log SET severity='exception' WHERE status='exception'")
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS ix_sched_log ON schedule_log(ts DESC)")
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS ix_sched_log_sev ON schedule_log(severity, ts DESC)")
        self._conn.commit()

    #: Which class each status belongs to. `event` is the routine narrative, `error` is
    #: a run that did not do what it said, `exception` is the bridge itself misbehaving
    #: — a bug, not a condition. Anything unlisted is an event: a new status should not
    #: silently claim the scarce error budget.
    LOG_SEVERITY: dict[str, str] = {
        "error": "error", "failed": "error", "missed": "error",
        "exception": "exception",
    }

    #: Rows kept per class. The error and exception budgets are small in absolute terms
    #: and enormous relative to how often they should occur — which is the point: a
    #: chatty `gated` stream can no longer push a failure out of the record.
    LOG_CAP: dict[str, int] = {"event": 2000, "error": 1000, "exception": 500}

    def log_schedule_event(self, schedule_id: str, name: str, status: str,
                           result: str, now: float | None = None,
                           severity: str | None = None) -> None:
        """Record one schedule event, capped WITHIN its class (see LOG_CAP)."""
        sev = severity or self.LOG_SEVERITY.get(status, "event")
        if sev not in self.LOG_CAP:
            sev = "event"
        with self._lock:
            self._conn.execute(
                "INSERT INTO schedule_log(ts, schedule_id, name, status, result, severity) "
                "VALUES (?,?,?,?,?,?)",
                (float(now if now is not None else time.time()),
                 schedule_id, name, status, result, sev))
            # Per-class cap: pruning only within the class that just grew means routine
            # chatter cannot evict an error, which a single shared cap guaranteed.
            self._conn.execute(
                "DELETE FROM schedule_log WHERE severity=? AND id NOT IN "
                "(SELECT id FROM schedule_log WHERE severity=? ORDER BY ts DESC LIMIT ?)",
                (sev, sev, self.LOG_CAP[sev]))
            self._conn.commit()

    def schedule_log(self, *, limit: int = 100, schedule_id: str | None = None,
                     status: str | None = None,
                     severity: str | None = None) -> list[dict]:
        q = "SELECT ts, schedule_id, name, status, result, severity FROM schedule_log"
        clauses, args = [], []
        if schedule_id:
            clauses.append("schedule_id=?"); args.append(schedule_id)
        if status:
            clauses.append("status=?"); args.append(status)
        if severity:
            clauses.append("severity=?"); args.append(severity)
        if clauses:
            q += " WHERE " + " AND ".join(clauses)
        q += " ORDER BY ts DESC LIMIT ?"
        args.append(max(1, min(limit, 500)))
        with self._lock:
            cur = self._conn.execute(q, args)
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]

    # ── control audit trail (off-grid / reboot / mode / reserve / modbus) ──────
    def _migrate_control_log(self) -> None:
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS control_log(
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   ts REAL NOT NULL,
                   gateway_id TEXT,
                   source TEXT,
                   action TEXT NOT NULL,
                   detail TEXT,
                   result TEXT,
                   ok INTEGER)"""
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS ix_control_log ON control_log(ts DESC)")
        self._conn.commit()

    def log_control_event(self, action: str, *, gateway_id: str | None = None,
                          source: str = "ui", detail: str = "", result: str = "",
                          ok: bool | None = None, now: float | None = None) -> None:
        """Record one consequential control invocation. Never raises."""
        try:
            with self._lock:
                self._conn.execute(
                    "INSERT INTO control_log(ts, gateway_id, source, action, detail, "
                    "result, ok) VALUES (?,?,?,?,?,?,?)",
                    (float(now if now is not None else time.time()), gateway_id, source,
                     action, detail, result, None if ok is None else int(bool(ok))))
                # Cap the trail so it cannot grow without bound.
                self._conn.execute(
                    "DELETE FROM control_log WHERE id NOT IN "
                    "(SELECT id FROM control_log ORDER BY ts DESC LIMIT 2000)")
                self._conn.commit()
        except Exception:  # pragma: no cover — auditing must never break a control action
            pass

    def control_log(self, *, limit: int = 100, gateway_id: str | None = None,
                    action: str | None = None) -> list[dict]:
        q = ("SELECT ts, gateway_id, source, action, detail, result, ok "
             "FROM control_log")
        clauses, args = [], []
        if gateway_id:
            clauses.append("gateway_id=?"); args.append(gateway_id)
        if action:
            clauses.append("action=?"); args.append(action)
        if clauses:
            q += " WHERE " + " AND ".join(clauses)
        q += " ORDER BY ts DESC LIMIT ?"
        args.append(max(1, min(limit, 500)))
        with self._lock:
            cur = self._conn.execute(q, args)
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]

    # ── software version / update history (support bundle) ────────────────────
    def _migrate_version_history(self) -> None:
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS version_history(
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   ts REAL NOT NULL,
                   version TEXT,
                   build TEXT)"""
        )
        self._conn.commit()

    def record_version(self, version: str, build: str = "", now: float | None = None) -> bool:
        """Append a row only when version/build changed from the newest one — so this is an
        UPDATE history, not a per-boot log. Returns True if a new row was written."""
        try:
            with self._lock:
                cur = self._conn.execute(
                    "SELECT version, build FROM version_history ORDER BY ts DESC LIMIT 1")
                last = cur.fetchone()
                if last and last[0] == version and last[1] == (build or ""):
                    return False
                self._conn.execute(
                    "INSERT INTO version_history(ts, version, build) VALUES (?,?,?)",
                    (float(now if now is not None else time.time()), version, build or ""))
                self._conn.commit()
                return True
        except Exception:  # pragma: no cover
            return False

    def version_history(self, *, limit: int = 50) -> list[dict]:
        try:
            with self._lock:
                cur = self._conn.execute(
                    "SELECT ts, version, build FROM version_history ORDER BY ts DESC LIMIT ?",
                    (max(1, min(limit, 500)),))
                cols = [c[0] for c in cur.description]
                return [dict(zip(cols, r)) for r in cur.fetchall()]
        except Exception:  # pragma: no cover
            return []

    # ── disclaimer acknowledgements (unofficial-app modal) ─────────────────────
    def _migrate_disclaimer_acks(self) -> None:
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS disclaimer_acks(
                   client_id TEXT PRIMARY KEY,
                   ts REAL NOT NULL,
                   ip TEXT,
                   version TEXT)"""
        )
        self._conn.commit()

    def record_disclaimer_ack(self, client_id: str, *, ip: str = "",
                              version: str = "", now: float | None = None) -> None:
        """Persist that a browser agreed to the disclaimer (source of truth for don't-show-again)."""
        try:
            with self._lock:
                self._conn.execute(
                    "INSERT OR REPLACE INTO disclaimer_acks(client_id, ts, ip, version) "
                    "VALUES (?,?,?,?)",
                    (client_id, float(now if now is not None else time.time()), ip, version))
                self._conn.commit()
        except Exception:  # pragma: no cover
            pass

    def disclaimer_agreed(self, client_id: str) -> bool:
        """Has this client already agreed? (DB is authoritative — survives a localStorage clear.)"""
        if not client_id:
            return False
        try:
            with self._lock:
                cur = self._conn.execute(
                    "SELECT 1 FROM disclaimer_acks WHERE client_id=? LIMIT 1", (client_id,))
                return cur.fetchone() is not None
        except Exception:  # pragma: no cover
            return False

    # ── application logs (Logs tab) — durable in the DB, not a rewritten JSONL file ──
    def _migrate_app_logs(self) -> None:
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS app_logs(
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   ts REAL NOT NULL,
                   level TEXT,
                   level_no INTEGER,
                   name TEXT,
                   message TEXT)"""
        )
        self._conn.execute("CREATE INDEX IF NOT EXISTS ix_app_logs_ts ON app_logs(ts DESC)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS ix_app_logs_level ON app_logs(level_no)")
        self._conn.commit()

    #: Keep the newest this-many log rows. Bigger than the old 5,000-line file — it's a DB.
    _APP_LOG_CAP = 50000

    def log_line(self, ts: float, level: str, level_no: int, name: str,
                 message: str) -> None:
        """Append one log line. Retention is applied periodically (not every insert, so a
        burst is cheap). Never raises — logging must not break on a DB hiccup."""
        try:
            with self._lock:
                self._conn.execute(
                    "INSERT INTO app_logs(ts, level, level_no, name, message) "
                    "VALUES (?,?,?,?,?)",
                    (float(ts), level, int(level_no), name, message))
                self._app_log_writes = getattr(self, "_app_log_writes", 0) + 1
                if self._app_log_writes % 500 == 0:
                    self._conn.execute(
                        "DELETE FROM app_logs WHERE id NOT IN "
                        "(SELECT id FROM app_logs ORDER BY ts DESC LIMIT ?)",
                        (self._APP_LOG_CAP,))
                self._conn.commit()
        except Exception:  # pragma: no cover — logging must never raise
            pass

    def log_bulk(self, entries: list[dict]) -> int:
        """Batch-insert log rows (used to import the legacy JSONL file once). Returns count."""
        rows = [(float(e.get("ts") or 0), e.get("level") or "", int(e.get("level_no") or 0),
                 e.get("name") or "", e.get("message") or "") for e in entries]
        if not rows:
            return 0
        try:
            with self._lock:
                self._conn.executemany(
                    "INSERT INTO app_logs(ts, level, level_no, name, message) VALUES (?,?,?,?,?)",
                    rows)
                self._conn.execute(
                    "DELETE FROM app_logs WHERE id NOT IN "
                    "(SELECT id FROM app_logs ORDER BY ts DESC LIMIT ?)", (self._APP_LOG_CAP,))
                self._conn.commit()
            return len(rows)
        except Exception:  # pragma: no cover
            return 0

    def _app_logs_where(self, *, level_no_min: int, since: float | None,
                        until: float | None, name: str | None, search: str | None):
        clauses, args = [], []
        if level_no_min:
            clauses.append("level_no >= ?"); args.append(int(level_no_min))
        if since is not None:
            clauses.append("ts >= ?"); args.append(float(since))
        if until is not None:
            clauses.append("ts <= ?"); args.append(float(until))
        if name:
            clauses.append("name = ?"); args.append(name)
        if search:
            clauses.append("message LIKE ?"); args.append(f"%{search}%")
        return (" WHERE " + " AND ".join(clauses) if clauses else ""), args

    def logs(self, *, limit: int = 200, offset: int = 0, level_no_min: int = 0,
             since: float | None = None, until: float | None = None,
             name: str | None = None, search: str | None = None) -> list[dict]:
        """Newest-first page of log rows, with filters + offset pagination."""
        where, args = self._app_logs_where(level_no_min=level_no_min, since=since,
                                            until=until, name=name, search=search)
        q = ("SELECT ts, level, name, message FROM app_logs" + where +
             " ORDER BY ts DESC LIMIT ? OFFSET ?")
        args = args + [max(1, min(limit, 5000)), max(0, offset)]
        with self._lock:
            cur = self._conn.execute(q, args)
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]

    def logs_count(self, *, level_no_min: int = 0, since: float | None = None,
                   until: float | None = None, name: str | None = None,
                   search: str | None = None) -> int:
        """Total rows matching the filters — for pagination (has_more / total)."""
        where, args = self._app_logs_where(level_no_min=level_no_min, since=since,
                                           until=until, name=name, search=search)
        with self._lock:
            cur = self._conn.execute("SELECT COUNT(*) FROM app_logs" + where, args)
            return int(cur.fetchone()[0])

    def clear_logs(self) -> None:
        """Delete all app_logs rows (test isolation)."""
        try:
            with self._lock:
                self._conn.execute("DELETE FROM app_logs")
                self._conn.commit()
        except Exception:  # pragma: no cover
            pass

    def log_sources(self) -> list[str]:
        """Distinct logger names present — for the Source filter dropdown."""
        with self._lock:
            cur = self._conn.execute(
                "SELECT DISTINCT name FROM app_logs WHERE name IS NOT NULL ORDER BY name")
            return [r[0] for r in cur.fetchall()]

    # ── closed billing periods (FEAT-BILLING-SERVICE history) ──────────────────
    def _migrate_billing_periods(self) -> None:
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS billing_periods(
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   closed_at REAL NOT NULL,
                   gateway_id TEXT, meter_id TEXT, utility_id TEXT, tariff_id TEXT,
                   retailer TEXT, network TEXT, plan_version TEXT, tariff_name TEXT,
                   period_start REAL, period_end REAL,
                   import_kwh REAL, import_cost REAL, export_credit REAL,
                   demand_peak_kw REAL, demand_charge REAL,
                   bonus_credit REAL, export_charge REAL, fixed_total REAL, net_total REAL)"""
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS ix_billing_periods ON billing_periods(period_start DESC)")
        self._conn.commit()

    #: The columns a closed-period snapshot may set (besides the id + timestamps).
    _BILLING_PERIOD_COLS = (
        "gateway_id", "meter_id", "utility_id", "tariff_id", "retailer", "network",
        "plan_version", "tariff_name", "period_start", "period_end", "import_kwh",
        "import_cost", "export_credit", "demand_peak_kw", "demand_charge", "bonus_credit",
        "export_charge", "fixed_total", "net_total")

    def record_billing_period(self, **fields) -> None:
        """Persist one closed billing period (rollover / tariff change / manual close). Never
        raises; unknown fields are ignored. One row per (gateway_id, period_start): a manual
        early close writes a provisional row that the automatic rollover close later REPLACES
        with the final numbers, so there is never a duplicate for the same period."""
        try:
            cols = ["closed_at"] + [c for c in self._BILLING_PERIOD_COLS if c in fields]
            vals = [float(time.time())] + [fields[c] for c in self._BILLING_PERIOD_COLS if c in fields]
            with self._lock:
                # Replace any existing snapshot for the same (gateway, period_start).
                if fields.get("period_start") is not None:
                    self._conn.execute(
                        "DELETE FROM billing_periods WHERE IFNULL(gateway_id,'')=IFNULL(?,'') "
                        "AND period_start=?", (fields.get("gateway_id"), fields["period_start"]))
                self._conn.execute(
                    f"INSERT INTO billing_periods({','.join(cols)}) "
                    f"VALUES ({','.join('?' * len(cols))})", vals)
                self._conn.commit()
        except Exception:  # pragma: no cover — history must never break the tick
            pass

    def billing_periods(self, *, limit: int = 60, gateway_id: str | None = None) -> list[dict]:
        q = ("SELECT closed_at, gateway_id, meter_id, utility_id, tariff_id, retailer, "
             "network, plan_version, tariff_name, period_start, period_end, import_kwh, "
             "import_cost, export_credit, demand_peak_kw, demand_charge, bonus_credit, "
             "export_charge, fixed_total, net_total FROM billing_periods")
        args: list = []
        if gateway_id:
            q += " WHERE gateway_id=?"; args.append(gateway_id)
        q += " ORDER BY period_start DESC LIMIT ?"; args.append(max(1, min(limit, 200)))
        with self._lock:
            cur = self._conn.execute(q, args)
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]

    # ── CloudFront PoP edge metrics (FEAT-CLOUD-POP-METRICS) ────────────────────
    def _migrate_cloud_pop(self) -> None:
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS cloud_pop_samples(
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   ts REAL NOT NULL, pop TEXT, requests INTEGER DEFAULT 0,
                   hits INTEGER DEFAULT 0, misses INTEGER DEFAULT 0, trace_id TEXT)"""
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS ix_cloud_pop_ts ON cloud_pop_samples(ts DESC)")
        self._conn.commit()

    def record_cloud_pop(self, *, pop, requests=0, hits=0, misses=0, trace_id=None,
                         retain_days: int = 30, max_rows: int = 50000) -> None:
        """Append one CloudFront-edge sample (one per cloud poll). Disk-safe: purges rows older
        than ``retain_days`` AND caps the table at ``max_rows`` (oldest dropped). Never raises."""
        try:
            with self._lock:
                self._conn.execute(
                    "INSERT INTO cloud_pop_samples(ts, pop, requests, hits, misses, trace_id) "
                    "VALUES (?,?,?,?,?,?)",
                    (float(time.time()), pop, int(requests or 0), int(hits or 0),
                     int(misses or 0), trace_id))
                if retain_days:
                    self._conn.execute("DELETE FROM cloud_pop_samples WHERE ts < ?",
                                       (time.time() - retain_days * 86400,))
                if max_rows:
                    self._conn.execute(
                        "DELETE FROM cloud_pop_samples WHERE id NOT IN "
                        "(SELECT id FROM cloud_pop_samples ORDER BY ts DESC LIMIT ?)", (max_rows,))
                self._conn.commit()
        except Exception:  # pragma: no cover — metrics must never break the poll
            pass

    def cloud_pop_samples(self, *, since_ts: float | None = None, limit: int = 20000) -> list[dict]:
        q = "SELECT ts, pop, requests, hits, misses, trace_id FROM cloud_pop_samples"
        args: list = []
        if since_ts is not None:
            q += " WHERE ts >= ?"; args.append(float(since_ts))
        q += " ORDER BY ts ASC LIMIT ?"; args.append(max(1, min(limit, 100000)))
        with self._lock:
            cur = self._conn.execute(q, args)
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]

    # ── notification delivery log (FEAT-NOTIFY trigger engine) ─────────────────
    def _migrate_notify_log(self) -> None:
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS notify_log(
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   ts REAL NOT NULL,
                   event TEXT NOT NULL,
                   title TEXT,
                   message TEXT,
                   device TEXT,
                   ok INTEGER)"""
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS ix_notify_log ON notify_log(ts DESC)")
        self._conn.commit()

    def log_notify(self, event: str, *, title: str = "", message: str = "",
                   device: str = "", ok: bool | None = None, now: float | None = None) -> None:
        """Record one notification delivery (per device). Never raises."""
        try:
            with self._lock:
                self._conn.execute(
                    "INSERT INTO notify_log(ts, event, title, message, device, ok) "
                    "VALUES (?,?,?,?,?,?)",
                    (float(now if now is not None else time.time()), event, title, message,
                     device, None if ok is None else int(bool(ok))))
                self._conn.execute(
                    "DELETE FROM notify_log WHERE id NOT IN "
                    "(SELECT id FROM notify_log ORDER BY ts DESC LIMIT 2000)")
                self._conn.commit()
        except Exception:  # pragma: no cover — logging must never break a notification
            pass

    def notify_log(self, *, limit: int = 100, event: str | None = None) -> list[dict]:
        q = "SELECT ts, event, title, message, device, ok FROM notify_log"
        args: list = []
        if event:
            q += " WHERE event=?"; args.append(event)
        q += " ORDER BY ts DESC LIMIT ?"; args.append(max(1, min(limit, 500)))
        with self._lock:
            cur = self._conn.execute(q, args)
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]

    def notify_stats(self) -> list[dict]:
        """Per-event delivery count + last timestamp (successful or not)."""
        with self._lock:
            cur = self._conn.execute(
                "SELECT event, COUNT(*), MAX(ts), SUM(CASE WHEN ok=1 THEN 1 ELSE 0 END) "
                "FROM notify_log GROUP BY event ORDER BY MAX(ts) DESC")
            return [{"event": r[0], "count": r[1], "last_ts": r[2], "delivered": r[3] or 0}
                    for r in cur.fetchall()]

    # ── scheduled battery dispatches (for interruption reconcile) ──────────────
    def _migrate_occurrences(self) -> None:
        """The execution queue: one row per EXPECTED run of a schedule.

        This is the table that makes silence detectable. Until now a run that never
        happened left no trace — an outage, a failed action and a schedule nobody
        enabled were indistinguishable, because the only evidence of a run was the
        log line written *after* it succeeded. Recording what is expected, before it
        happens, turns "nothing in the log" from ambiguous into answerable.

        `occurrence_key` identifies one particular run — the date for a daily rule, the
        slot timestamp for cron/interval. It replaces `schedules.last_fired_day`, which
        could only say "something happened today" and could not distinguish a success
        from a user stopping it, nor survive a second gateway.

        UNIQUE(schedule_id, occurrence_key, gateway_id) is `max_instances` expressed in
        the schema: one run per rule per occurrence per gateway, enforced where it
        cannot be forgotten.
        """
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS occurrences(
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   schedule_id TEXT NOT NULL,
                   name TEXT,
                   gateway_id TEXT NOT NULL DEFAULT '',
                   occurrence_key TEXT NOT NULL,
                   due_ts REAL NOT NULL,
                   window_end_ts REAL,
                   status TEXT NOT NULL DEFAULT 'pending',
                   attempts INTEGER NOT NULL DEFAULT 0,
                   first_attempt_ts REAL, last_attempt_ts REAL,
                   started_ts REAL, ended_ts REAL,
                   outcome TEXT, reason TEXT,
                   created_ts REAL NOT NULL,
                   UNIQUE(schedule_id, occurrence_key, gateway_id))"""
        )
        # Finding the work to do, and the work that silently did not happen, are the
        # two hot queries; both filter on status.
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS ix_occ_status ON occurrences(status, window_end_ts)")
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS ix_occ_schedule ON occurrences(schedule_id, due_ts)")
        # BR-50: what the device was set to BEFORE this run overrode it, so exit can put
        # it back. Stored on the run rather than in memory because the thing that has to
        # survive is a restart — an override the bridge forgets is an override that
        # becomes permanent.
        cols = [r[1] for r in self._conn.execute("PRAGMA table_info(occurrences)")]
        if "prior_state" not in cols:
            self._conn.execute("ALTER TABLE occurrences ADD COLUMN prior_state TEXT")
        self._conn.commit()

    def set_prior_state(self, occ_id: int, prior: dict) -> None:
        """Record what to put back. Written once, at the moment of override."""
        with self._lock:
            self._conn.execute(
                "UPDATE occurrences SET prior_state=COALESCE(prior_state,?) WHERE id=?",
                (json.dumps(prior), int(occ_id)))
            self._conn.commit()

    def prior_state(self, *, schedule_id: str, gateway_id: str,
                    occurrence_key: str) -> dict | None:
        """The captured pre-override state for one run, if any."""
        with self._lock:
            row = self._conn.execute(
                "SELECT prior_state FROM occurrences WHERE schedule_id=? AND gateway_id=? "
                "AND occurrence_key=?",
                (schedule_id, gateway_id or "", occurrence_key)).fetchone()
        if not row or not row[0]:
            return None
        try:
            return json.loads(row[0])
        except (ValueError, TypeError):
            return None

    def _migrate_dispatches(self) -> None:
        """One row per force dispatch a schedule starts. Left 'active' if the bridge
        stops before a clean release, so a boot reconcile can detect interruptions."""
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS dispatches(
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   schedule_id TEXT, name TEXT, gateway_id TEXT, host TEXT,
                   direction TEXT, watts INTEGER, power_mode TEXT, target_soc INTEGER,
                   window_start_ts REAL, window_end_ts REAL,
                   started_ts REAL, ended_ts REAL,
                   status TEXT NOT NULL DEFAULT 'active')"""
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS ix_dispatch_active ON dispatches(status)")
        self._conn.commit()

    # ── occurrences: the execution queue ─────────────────────────────────────
    #: Terminal states. An occurrence in one of these is finished and is never
    #: retried — `stopped` included, because an operator's decision is not a failure
    #: to recover from.
    OCC_TERMINAL = ("ok", "missed", "skipped", "stopped", "unknown")

    #: `paused` is deliberately NOT terminal, and that is the whole difference between
    #: it and `stopped`. Stop releases control and ends the occurrence; Pause releases
    #: control and KEEPS it, so Resume can re-enter while the window is still open.
    #: Overloading one verb with both meanings is what left this bridge unable to
    #: either resume or explain itself.
    OCC_RESUMABLE = ("paused", "failed")

    def claim_occurrence(self, *, schedule_id: str, name: str, gateway_id: str,
                         occurrence_key: str, due_ts: float,
                         window_end_ts: float | None, now=None) -> dict | None:
        """Register that this run is EXPECTED, and return it. Idempotent.

        Returns the row whether it was just created or already existed, so a caller
        can see a run that is already finished and leave it alone. Returns None only
        if the row cannot be read back.

        The UNIQUE constraint does the work: two ticks racing, or two gateways being
        evaluated concurrently, cannot produce two runs of the same occurrence.
        """
        ts = float(now if now is not None else time.time())
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO occurrences"
                "(schedule_id, name, gateway_id, occurrence_key, due_ts, window_end_ts,"
                " status, created_ts) VALUES(?,?,?,?,?,?, 'pending', ?)",
                (schedule_id, name, gateway_id or "", occurrence_key, float(due_ts),
                 None if window_end_ts is None else float(window_end_ts), ts))
            self._conn.commit()
            cur = self._conn.execute(
                "SELECT * FROM occurrences WHERE schedule_id=? AND occurrence_key=? "
                "AND gateway_id=?", (schedule_id, occurrence_key, gateway_id or ""))
            row = cur.fetchone()
            if row is None:
                return None
            return dict(zip([c[0] for c in cur.description], row))

    def coalesce_occurrences(self, *, schedule_id: str, gateway_id: str,
                             keep_id: int, keep_due_ts: float, now=None) -> list[dict]:
        """Collapse an older backlog into the run about to happen (`coalesce`).

        A bridge that was down for two hours comes back to find several of a rule's
        slots still open. APScheduler's `coalesce` says: do the work ONCE, not once per
        slot missed — replaying a backlog of battery setpoints is worse than skipping
        it, because every one of those windows was decided against conditions that have
        since moved on.

        Older OPEN runs for the same rule on the same gateway are therefore closed as
        `skipped`, naming the run that absorbed them, and the newest proceeds. Runs
        already terminal are left alone; nothing that recorded a verdict is rewritten.
        Returns what was collapsed so the caller can say so out loud.
        """
        ts = float(now if now is not None else time.time())
        marks = ",".join("?" * len(self.OCC_TERMINAL))
        with self._lock:
            cur = self._conn.execute(
                f"SELECT * FROM occurrences WHERE schedule_id=? AND gateway_id=? "
                f"AND id<>? AND due_ts<=? AND status NOT IN ({marks})",
                (schedule_id, gateway_id or "", int(keep_id), float(keep_due_ts),
                 *self.OCC_TERMINAL))
            cols = [c[0] for c in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
            if not rows:
                return []
            keep_key = self._conn.execute(
                "SELECT occurrence_key FROM occurrences WHERE id=?", (int(keep_id),)
            ).fetchone()
            label = keep_key[0] if keep_key else str(keep_id)
            self._conn.executemany(
                "UPDATE occurrences SET status='skipped', outcome='skipped', "
                "reason=?, ended_ts=? WHERE id=?",
                [(f"coalesced into the run for {label}", ts, r["id"]) for r in rows])
            self._conn.commit()
        return rows

    def occurrence_attempt(self, occ_id: int, *, now=None) -> None:
        """Record that an attempt is starting. Counting attempts is what separates
        'failed once, will retry' from 'tried eleven times and is thrashing'."""
        ts = float(now if now is not None else time.time())
        with self._lock:
            self._conn.execute(
                "UPDATE occurrences SET status='running', attempts=attempts+1, "
                "last_attempt_ts=?, first_attempt_ts=COALESCE(first_attempt_ts,?), "
                "started_ts=COALESCE(started_ts,?) WHERE id=?", (ts, ts, ts, occ_id))
            self._conn.commit()

    def finish_occurrence(self, occ_id: int, *, status: str, outcome: str = "",
                          reason: str = "", now=None) -> None:
        """Close an occurrence with a verdict and, where it matters, a reason.

        `reason` is not decoration: `skipped` without one is indistinguishable from a
        bug, and 'why did my rule not run' is the question this table exists to answer.
        """
        ts = float(now if now is not None else time.time())
        with self._lock:
            self._conn.execute(
                "UPDATE occurrences SET status=?, outcome=?, reason=?, ended_ts=? "
                "WHERE id=?", (status, outcome or "", reason or "", ts, occ_id))
            self._conn.commit()

    def reopen_occurrence(self, occ_id: int) -> None:
        """Return a run to `pending` so the next tick retries it within its window.

        This is the whole of retry-within-window and resume-after-stop: nothing is
        re-scheduled, the row simply becomes claimable again and the existing tick
        picks it up. `attempts` is deliberately NOT reset — the history of how hard
        this has been tried is the evidence a crash loop is visible by.
        """
        with self._lock:
            self._conn.execute(
                "UPDATE occurrences SET status='pending', ended_ts=NULL WHERE id=?",
                (occ_id,))
            self._conn.commit()

    def pause_occurrence(self, occ_id: int, *, reason: str = "", now=None) -> None:
        """Release control but KEEP the occurrence, so Resume can re-enter it.

        Distinct from `finish_occurrence(status='stopped')`, which ends it. The pair
        exists because one verb cannot mean both "I am done with this" and "hold my
        place" without the user guessing which they got.
        """
        ts = float(now if now is not None else time.time())
        with self._lock:
            self._conn.execute(
                "UPDATE occurrences SET status='paused', ended_ts=?, "
                "reason=? WHERE id=?", (ts, reason or "paused by user", occ_id))
            self._conn.commit()

    def resume_occurrence(self, occ_id: int, *, now=None) -> tuple[bool, str]:
        """Re-enter a paused occurrence, but only while its window is still open.

        Returns (ok, reason). Refusing after the window has closed is the point: a
        resume that silently did nothing would be worse than an error, because the
        operator would believe the rule was running again.
        """
        ts = float(now if now is not None else time.time())
        with self._lock:
            cur = self._conn.execute(
                "SELECT status, window_end_ts FROM occurrences WHERE id=?", (occ_id,))
            row = cur.fetchone()
            if row is None:
                return False, "no such occurrence"
            status, wend = row[0], row[1]
            if status != "paused":
                return False, f"not paused (is '{status}')"
            if wend is not None and float(wend) <= ts:
                return False, "window has closed — resume is only valid inside it"
            self._conn.execute(
                "UPDATE occurrences SET status='pending', ended_ts=NULL, reason='' "
                "WHERE id=?", (occ_id,))
            self._conn.commit()
            return True, ""

    def resolve_paused_on_boot(self, *, now=None) -> list[dict]:
        """A restart while paused resolves to terminal.

        Pause is in-flight intent held by a running process. Once that process is
        gone, nobody is holding the place any more, and a pause that outlives its
        process becomes an occurrence nobody can account for — the same silent state
        this table exists to remove. So on boot they become `stopped`, with the reason
        recorded rather than inferred.
        """
        ts = float(now if now is not None else time.time())
        with self._lock:
            cur = self._conn.execute("SELECT * FROM occurrences WHERE status='paused'")
            cols = [c[0] for c in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
            if rows:
                self._conn.execute(
                    "UPDATE occurrences SET status='stopped', ended_ts=?, "
                    "reason='paused when the bridge restarted — resolved to stopped' "
                    "WHERE status='paused'", (ts,))
                self._conn.commit()
            return rows

    def sweep_missed(self, *, grace_s: float = 0.0, now=None) -> list[dict]:
        """Close out runs whose window shut while they were still pending.

        This is the detection the whole table is for. A run that never happened
        produces no event by definition, so it can only be found by comparing what was
        expected against what completed — which requires the expectation to have been
        written down first.

        `grace_s` is `misfire_grace_time`: how late is still worth running. Rows inside
        the grace are left alone for the tick to catch up.
        """
        ts = float(now if now is not None else time.time())
        cutoff = ts - max(0.0, float(grace_s))
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM occurrences WHERE status IN ('pending','running','failed') "
                "AND window_end_ts IS NOT NULL AND window_end_ts < ?", (cutoff,))
            # 'paused' is excluded on purpose: a user holding their place is not a
            # missed run. It resolves to 'stopped' at the next boot instead.
            cols = [c[0] for c in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
            for r in rows:
                self._conn.execute(
                    "UPDATE occurrences SET status='missed', ended_ts=?, "
                    "reason=CASE WHEN ifnull(reason,'')='' THEN ? ELSE reason END "
                    "WHERE id=?",
                    (ts, f"window closed at {r['window_end_ts']:.0f} with "
                          f"{r['attempts']} attempt(s) and no success", r["id"]))
            self._conn.commit()
            return rows

    def due_occurrences(self, *, gateway_id: str | None = None, now=None) -> list[dict]:
        """Runs that should be acted on right now: claimed, not finished, window open."""
        ts = float(now if now is not None else time.time())
        q = ("SELECT * FROM occurrences WHERE status IN ('pending','failed') "
             "AND due_ts <= ? AND (window_end_ts IS NULL OR window_end_ts > ?)")
        args: list = [ts, ts]
        if gateway_id is not None:
            q += " AND gateway_id=?"
            args.append(gateway_id)
        q += " ORDER BY due_ts"
        with self._lock:
            cur = self._conn.execute(q, args)
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]

    def occurrences_for(self, schedule_id: str, *, status: str | None = None) -> list[dict]:
        """Rows for one schedule, newest first. Used to find a paused run, which
        `due_occurrences` deliberately excludes — paused work is not claimable."""
        q = "SELECT * FROM occurrences WHERE schedule_id=?"
        args: list = [schedule_id]
        if status:
            q += " AND status=?"
            args.append(status)
        q += " ORDER BY due_ts DESC"
        with self._lock:
            cur = self._conn.execute(q, args)
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]

    def occurrences_recent(self, *, schedule_id: str | None = None,
                           limit: int = 50) -> list[dict]:
        """The execution queue as a feed: pending, running and finished, newest first."""
        q = "SELECT * FROM occurrences"
        args: list = []
        if schedule_id:
            q += " WHERE schedule_id=?"
            args.append(schedule_id)
        q += " ORDER BY due_ts DESC LIMIT ?"
        args.append(max(1, min(int(limit), 500)))
        with self._lock:
            cur = self._conn.execute(q, args)
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]

    def occurrence_stats(self, schedule_id: str | None = None) -> list[dict]:
        """Per-rule execution history: runs, first, last, last failure.

        Reads off occurrences rather than `schedule_log`, where execution was 2% of
        rows and a FIFO cap evicted it before it aged out.
        """
        q = ("SELECT schedule_id, name, COUNT(*) AS runs, "
             " SUM(status='ok') AS ok, SUM(status='missed') AS missed, "
             " SUM(status IN ('failed','unknown')) AS failed, "
             " SUM(status='skipped') AS skipped, SUM(status='stopped') AS stopped, "
             " SUM(status='paused') AS paused, "
             " MIN(due_ts) AS first_ts, MAX(due_ts) AS last_ts, "
             " MAX(CASE WHEN status IN ('failed','unknown','missed') THEN due_ts END) "
             "   AS last_failure_ts "
             "FROM occurrences")
        args: list = []
        if schedule_id:
            q += " WHERE schedule_id=?"
            args.append(schedule_id)
        q += " GROUP BY schedule_id ORDER BY runs DESC"
        with self._lock:
            cur = self._conn.execute(q, args)
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]

    def prune_occurrences(self, *, keep_days: int = 90, now=None) -> int:
        """Age out finished runs. Unlike schedule_log's row cap, this prunes by TIME
        and only terminal rows, so a burst of noise cannot evict real history."""
        ts = float(now if now is not None else time.time())
        cutoff = ts - max(1, int(keep_days)) * 86400.0
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM occurrences WHERE due_ts < ? AND status NOT IN "
                "('pending','running')", (cutoff,))
            self._conn.commit()
            return cur.rowcount or 0

    def record_dispatch(self, *, schedule_id, name, gateway_id, host, direction,
                        watts, power_mode, target_soc, window_start_ts, window_end_ts,
                        now=None) -> int:
        """Mark a dispatch active. Any earlier 'active' row for the same gateway/host is
        closed first — a gateway holds at most one force dispatch at a time."""
        ts = float(now if now is not None else time.time())
        with self._lock:
            self._conn.execute(
                "UPDATE dispatches SET status='superseded', ended_ts=? "
                "WHERE status='active' AND ifnull(gateway_id,'')=ifnull(?,'') "
                "AND ifnull(host,'')=ifnull(?,'')", (ts, gateway_id, host))
            cur = self._conn.execute(
                "INSERT INTO dispatches(schedule_id, name, gateway_id, host, direction, "
                "watts, power_mode, target_soc, window_start_ts, window_end_ts, "
                "started_ts, status) VALUES (?,?,?,?,?,?,?,?,?,?,?, 'active')",
                (schedule_id, name, gateway_id, host, direction, int(watts or 0),
                 power_mode, int(target_soc or 0), window_start_ts, window_end_ts, ts))
            self._conn.commit()
            return int(cur.lastrowid)

    def end_dispatch(self, dispatch_id: int, *, status: str = "ended", now=None) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE dispatches SET status=?, ended_ts=? WHERE id=?",
                (status, float(now if now is not None else time.time()), int(dispatch_id)))
            self._conn.commit()

    def end_active_dispatches(self, *, host=None, gateway_id=None,
                              status: str = "ended", now=None) -> int:
        """Close any 'active' rows (optionally scoped to a host/gateway) — used on a
        clean release when the caller does not hold the row id."""
        ts = float(now if now is not None else time.time())
        q = "UPDATE dispatches SET status=?, ended_ts=? WHERE status='active'"
        args = [status, ts]
        if host is not None:
            q += " AND ifnull(host,'')=ifnull(?,'')"; args.append(host)
        if gateway_id is not None:
            q += " AND ifnull(gateway_id,'')=ifnull(?,'')"; args.append(gateway_id)
        with self._lock:
            cur = self._conn.execute(q, args)
            self._conn.commit()
            return cur.rowcount

    def active_dispatches(self, *, host=None) -> list[dict]:
        q = "SELECT * FROM dispatches WHERE status='active'"
        args = []
        if host is not None:
            q += " AND ifnull(host,'')=ifnull(?,'')"; args.append(host)
        q += " ORDER BY started_ts DESC"
        with self._lock:
            cur = self._conn.execute(q, args)
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]

    def start_bms_session(self, *, gateway_id=None, apower_sn=None, dev_id=1,
                          interval_s=15.0, planned=20, label=None, now=None) -> int:
        ts = int(now if now is not None else time.time())
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO bms_sessions(started_ts, gateway_id, apower_sn, dev_id, "
                "interval_s, planned, label) VALUES (?,?,?,?,?,?,?)",
                (ts, gateway_id, apower_sn, dev_id, interval_s, planned, label))
            self._conn.commit()
            return int(cur.lastrowid)

    def add_bms_sample(self, session_id: int, cells: dict, ts=None) -> None:
        """Store one snapshot. Cell arrays are JSON; everything else is nullable."""
        ts = int(ts if ts is not None else time.time())
        volts = cells.get("batVolt") if isinstance(cells.get("batVolt"), list) else None
        temps = cells.get("batTemp") if isinstance(cells.get("batTemp"), list) else None
        with self._lock:
            self._conn.execute(
                "INSERT INTO bms_samples(session_id, ts, soc, soh, pack_v, current_a, "
                "volts, temps) VALUES (?,?,?,?,?,?,?,?)",
                (session_id, ts, _num(cells.get("batSoc")), _num(cells.get("batSoh")),
                 _num(cells.get("batTotalVolt")), _num(cells.get("currGrp")),
                 json.dumps(volts) if volts else None,
                 json.dumps(temps) if temps else None))
            self._conn.commit()

    def end_bms_session(self, session_id: int, now=None) -> None:
        with self._lock:
            self._conn.execute("UPDATE bms_sessions SET ended_ts=? WHERE id=?",
                               (int(now if now is not None else time.time()), session_id))
            self._conn.commit()

    def bms_sessions(self, limit: int = 200, apower_sn: str | None = None) -> list[dict]:
        """Session list, newest first, with the actual sample count and span."""
        sql = ("SELECT s.*, COUNT(x.id) AS samples, MIN(x.ts) AS first_ts, "
               "MAX(x.ts) AS last_ts FROM bms_sessions s "
               "LEFT JOIN bms_samples x ON x.session_id = s.id")
        args: list = []
        if apower_sn:
            sql += " WHERE s.apower_sn = ?"
            args.append(apower_sn)
        sql += " GROUP BY s.id ORDER BY s.started_ts DESC LIMIT ?"
        args.append(limit)
        with self._lock:
            cur = self._conn.execute(sql, args)
            cols = [c[0] for c in cur.description]
            rows = cur.fetchall()
        return [dict(zip(cols, r)) for r in rows]

    def bms_session(self, session_id: int) -> dict | None:
        """One session with its samples, cell arrays parsed back to lists."""
        with self._lock:
            hc = self._conn.execute("SELECT * FROM bms_sessions WHERE id=?", (session_id,))
            hcols = [c[0] for c in hc.description]
            head = hc.fetchone()
            if head is None:
                return None
            sc = self._conn.execute(
                "SELECT * FROM bms_samples WHERE session_id=? ORDER BY ts", (session_id,))
            scols = [c[0] for c in sc.description]
            rows = sc.fetchall()
        out = dict(zip(hcols, head))
        samples = []
        for r in rows:
            d = dict(zip(scols, r))
            for key in ("volts", "temps"):
                try:
                    d[key] = json.loads(d[key]) if d[key] else None
                except (TypeError, ValueError):
                    d[key] = None
            samples.append(d)
        out["samples"] = samples
        return out

    def delete_bms_session(self, session_id: int) -> int:
        with self._lock:
            self._conn.execute("DELETE FROM bms_samples WHERE session_id=?", (session_id,))
            cur = self._conn.execute("DELETE FROM bms_sessions WHERE id=?", (session_id,))
            self._conn.commit()
            return cur.rowcount

    def _migrate_tariff_dates(self) -> None:
        """Tariff effective_start / effective_end (ISO dates) — supersede, never delete."""
        cols = [r[1] for r in self._conn.execute("PRAGMA table_info(tariffs)")]
        for c in ("effective_start", "effective_end"):
            if c not in cols:
                self._conn.execute(f"ALTER TABLE tariffs ADD COLUMN {c} TEXT")
        self._conn.commit()

    def _migrate_service_details(self) -> None:
        """Richer service fields ported from the Modbus bridge: a PTO reference on the
        meter (pairs with the existing pto_status) and a free-text export-restriction note
        on the utility."""
        mcols = [r[1] for r in self._conn.execute("PRAGMA table_info(meters)")]
        if "pto_reference" not in mcols:
            self._conn.execute("ALTER TABLE meters ADD COLUMN pto_reference TEXT NOT NULL DEFAULT ''")
        ucols = [r[1] for r in self._conn.execute("PRAGMA table_info(utilities)")]
        if "export_note" not in ucols:
            self._conn.execute("ALTER TABLE utilities ADD COLUMN export_note TEXT NOT NULL DEFAULT ''")
        # Provider (retailer) tenure — effective dates so a provider switch is recorded as
        # supersede-don't-delete (AU/NZ retailer switching). Mirrors tariff effective dates.
        for c in ("effective_start", "effective_end"):
            if c not in ucols:
                self._conn.execute(f"ALTER TABLE utilities ADD COLUMN {c} TEXT")
        self._conn.commit()

    # ── app_config (generic KV; JSON-encoded values) ─────────────────────────
    def _migrate_app_config(self) -> None:
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS app_config(
                   key TEXT PRIMARY KEY,
                   value TEXT NOT NULL,
                   updated_at REAL NOT NULL DEFAULT 0)""")
        self._conn.commit()

    def get_config(self, key: str, default=None):
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM app_config WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def set_config(self, key: str, value: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO app_config(key,value,updated_at) VALUES (?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
                "updated_at=excluded.updated_at",
                (key, value, time.time()))
            self._conn.commit()

    def prune(self, retention_days: int, now: int) -> int:
        """Delete rows older than ``retention_days``. Returns rows deleted."""
        cutoff = now - retention_days * 86400
        with self._lock:
            cur = self._conn.execute("DELETE FROM metrics WHERE ts < ?", (cutoff,))
            self._conn.commit()
            return cur.rowcount

    def info(self, gateway: str | None = None) -> dict:
        if gateway is not None:
            sql = "SELECT COUNT(*), MIN(ts), MAX(ts) FROM metrics WHERE gateway_id = ?"
            args: tuple = (gateway,)
        else:
            sql, args = "SELECT COUNT(*), MIN(ts), MAX(ts) FROM metrics", ()
        with self._lock:
            row = self._conn.execute(sql, args).fetchone()
        db_bytes = None
        if self.path != ":memory:":
            try:
                db_bytes = Path(self.path).stat().st_size
            except OSError:
                db_bytes = None
        return {
            "count": row[0] or 0,
            "first_ts": row[1],
            "last_ts": row[2],
            "db_bytes": db_bytes,
        }

    # ── admin: storage insight + backup / restore / vacuum ────────────────────
    #: Tables surfaced in the storage view, richest-first bias handled at call time.
    _STORAGE_TABLES = ("metrics", "bms_samples", "bms_sessions", "dispatches",
                       "schedule_log", "control_log", "app_config", "gateways",
                       "sites", "meters", "utilities", "tariffs", "schedules",
                       "notify_devices", "ha_instances", "ha_exposed")
    #: Of those, the time-series tables whose age span is worth showing.
    _TS_TABLES = frozenset({"metrics", "bms_samples", "schedule_log", "control_log",
                            "dispatches"})

    def storage_stats(self) -> dict:
        """Disk-usage insight: total DB bytes + SQLite page accounting + per-table row
        counts and time span (days). Read-only; never raises on a missing table."""
        db_bytes = page_size = page_count = freelist = None
        if self.path != ":memory:":
            try:
                db_bytes = Path(self.path).stat().st_size
            except OSError:
                db_bytes = None
        tables: list[dict] = []
        with self._lock:
            try:
                page_size = self._conn.execute("PRAGMA page_size").fetchone()[0]
                page_count = self._conn.execute("PRAGMA page_count").fetchone()[0]
                freelist = self._conn.execute("PRAGMA freelist_count").fetchone()[0]
            except Exception:  # pragma: no cover
                pass
            existing = {r[0] for r in self._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
            for t in self._STORAGE_TABLES:
                if t not in existing:
                    continue
                try:
                    rows = self._conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                except Exception:  # pragma: no cover
                    rows = None
                span = None
                if t in self._TS_TABLES and rows:
                    try:
                        lo, hi = self._conn.execute(
                            f"SELECT MIN(ts), MAX(ts) FROM {t}").fetchone()
                        if lo and hi:
                            span = round((hi - lo) / 86400, 1)
                    except Exception:  # pragma: no cover
                        span = None
                tables.append({"name": t, "rows": rows, "span_days": span})
        tables.sort(key=lambda x: (x["rows"] or 0), reverse=True)
        return {"db_bytes": db_bytes, "page_size": page_size, "page_count": page_count,
                "freelist_count": freelist, "tables": tables}

    def backup_to(self, dest_path: str) -> int:
        """Write a CONSISTENT snapshot of the live DB to ``dest_path`` (SQLite online-backup
        API — safe while the bridge keeps running). Returns the snapshot size in bytes."""
        dst = sqlite3.connect(dest_path)
        try:
            with self._lock:
                self._conn.backup(dst)
        finally:
            dst.close()
        return Path(dest_path).stat().st_size

    def restore_from(self, src_path: str) -> None:
        """Replace the live DB CONTENT with a backup file, in place, via the online-backup
        API — atomic within the live connection, so no reconnect/restart is needed and open
        handles keep working. DESTRUCTIVE: the current content is overwritten."""
        src = sqlite3.connect(src_path)
        try:
            with self._lock:
                src.backup(self._conn)
                self._conn.commit()
        finally:
            src.close()

    def vacuum(self) -> int:
        """Compact the DB file (reclaim freelist pages). Returns the new size in bytes."""
        with self._lock:
            prev = self._conn.isolation_level
            try:
                self._conn.isolation_level = None      # VACUUM can't run in a transaction
                self._conn.execute("VACUUM")
            finally:
                self._conn.isolation_level = prev
        try:
            return Path(self.path).stat().st_size
        except OSError:
            return 0

    def close(self) -> None:
        with self._lock:
            self._conn.close()


def _tiers_json(tiers) -> str | None:
    """Serialise the tier block, keeping only the four known array keys.

    Anything unexpected → None. Recording nothing is better than recording
    something that later reads as data.
    """
    if not isinstance(tiers, dict):
        return None
    kept = {k: v for k, v in tiers.items() if k in _TIER_KEYS and isinstance(v, list)}
    if not kept:
        return None
    try:
        return json.dumps(kept, separators=(",", ":"))
    except (TypeError, ValueError):
        return None


def _num(v):
    """Coerce to float for the numeric columns; None/non-numeric → None (NULL)."""
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _round(v, ndigits):
    if v is None:
        return None
    r = round(float(v), ndigits)
    return int(r) if ndigits == 0 else r


# -- process-global singleton (app + poller share ONE instance) -----------------
_stores: dict[str, MetricsStore] = {}
_stores_lock = threading.Lock()


def get_store(settings: Settings) -> MetricsStore | None:
    """Return the shared store, or None when metrics are disabled. Lazily created and
    keyed by ``metrics_db`` so the app and poller share a single instance/connection."""
    if not metrics_active(settings):
        return None
    key = settings.metrics_db
    with _stores_lock:
        store = _stores.get(key)
        if store is None:
            store = MetricsStore(key)
            _stores[key] = store
        return store


def reset_store() -> None:
    """Test hook — close and forget all cached stores."""
    with _stores_lock:
        for store in _stores.values():
            try:
                store.close()
            except Exception:  # noqa: BLE001
                pass
        _stores.clear()
