"""MetricsStore unit tests — insert / query (raw + bucketed) / prune / info."""

from franklinwh_local_bridge.db import MetricsStore


def _seed(store, base):
    for i in range(10):
        store.insert(
            {"soc": 50 + i, "grid_w": i * 10, "solar_w": 0,
             "battery_w": -i, "load_w": 100, "generator_w": 0, "mode": "Self"},
            base + i * 60,
        )


def test_insert_and_query_raw():
    s = MetricsStore(":memory:")
    _seed(s, 1_000_000)
    rows = s.query(1_000_000, 1_000_000 + 9 * 60, None)
    assert len(rows) == 10
    assert rows[0]["soc"] == 50.0
    assert rows[0]["mode"] == "Self"           # raw includes mode
    assert rows[-1]["grid_w"] == 90            # watts rounded to 0dp
    assert rows[0]["ts"] == 1_000_000
    s.close()


def test_query_bucketed_aggregates():
    s = MetricsStore(":memory:")
    _seed(s, 1_000_000)                        # 10 rows spanning 9 minutes
    raw = s.query(1_000_000, 1_000_000 + 9 * 60, None)
    bucketed = s.query(1_000_000, 1_000_000 + 9 * 60, 300)  # 5-min buckets
    assert 0 < len(bucketed) < len(raw)        # fewer, averaged rows
    assert "mode" not in bucketed[0]           # bucketed drops mode
    for row in bucketed:
        assert row["soc"] is not None
    s.close()


def test_missing_fields_become_null():
    s = MetricsStore(":memory:")
    s.insert({"soc": 42}, 2_000_000)           # only soc present
    row = s.query(1_999_999, 2_000_001, None)[0]
    assert row["soc"] == 42.0
    assert row["grid_w"] is None
    assert row["mode"] is None
    s.close()


def test_prune_deletes_old_rows():
    s = MetricsStore(":memory:")
    _seed(s, 1_000_000)
    info_before = s.info()
    assert info_before["count"] == 10
    deleted = s.prune(0, 1_000_000 + 9 * 60 + 1)   # retention 0 days → all older
    assert deleted == 10
    assert s.info()["count"] == 0
    s.close()


def test_info_counts(tmp_path):
    path = str(tmp_path / "metrics.db")
    s = MetricsStore(path)
    _seed(s, 1_000_000)
    info = s.info()
    assert info["count"] == 10
    assert info["first_ts"] == 1_000_000
    assert info["last_ts"] == 1_000_000 + 9 * 60
    assert info["db_bytes"] and info["db_bytes"] > 0
    s.close()


def test_file_backed_roundtrip(tmp_path):
    path = str(tmp_path / "metrics.db")
    s = MetricsStore(path)
    _seed(s, 1_000_000)
    s.close()
    s2 = MetricsStore(path)                     # reopen — data persists
    assert s2.info()["count"] == 10
    s2.close()


def test_gateway_id_column_present():
    s = MetricsStore(":memory:")
    cols = [r[1] for r in s._conn.execute("PRAGMA table_info(metrics)")]
    assert "gateway_id" in cols
    s.close()


def test_gateway_filtered_query():
    s = MetricsStore(":memory:")
    t = 1_000_000
    s.insert({"soc": 50, "grid_w": 1, "mode": "Self"}, t, gateway_id="SER123")
    s.insert({"soc": 60, "grid_w": 2, "mode": "Self"}, t + 1, gateway_id="SER999")
    # Unfiltered sees both; per-gateway filter isolates each.
    assert len(s.query(t - 60, t + 60, None)) == 2
    assert len(s.query(t - 60, t + 60, None, gateway="SER123")) == 1
    assert len(s.query(t - 60, t + 60, None, gateway="SER999")) == 1
    assert len(s.query(t - 60, t + 60, None, gateway="NOPE")) == 0
    # Bucketed path also honors the gateway filter.
    assert len(s.query(t - 60, t + 60, 300, gateway="SER123")) == 1
    # Per-gateway info count.
    assert s.info(gateway="SER123")["count"] == 1
    s.close()


def test_migration_adds_gateway_id_to_legacy_db(tmp_path):
    """A pre-migration DB (no gateway_id) gets the column added on reopen; old rows
    survive with NULL gateway_id and are visible to an unfiltered query."""
    import sqlite3
    path = str(tmp_path / "legacy.db")
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE metrics(id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL,"
        " soc REAL, grid_w REAL, solar_w REAL, battery_w REAL, load_w REAL,"
        " generator_w REAL, mode TEXT)")
    conn.execute("INSERT INTO metrics(ts, soc) VALUES (1000000, 42)")
    conn.commit()
    conn.close()

    s = MetricsStore(path)                       # opening runs the migration
    cols = [r[1] for r in s._conn.execute("PRAGMA table_info(metrics)")]
    assert "gateway_id" in cols
    assert s.info()["count"] == 1                # legacy row preserved
    s.close()


# -- tariff-tier accumulators (cmdType 1301) ---------------------------------
def _tiers(**per_tier):
    """A 1301-shaped tier block: four 7-element channel arrays."""
    block = {t: [0.0] * 7 for t in ("sharp", "peak", "flat", "valley")}
    for tier, value in per_tier.items():
        block[tier] = [value] * 7
    return block


def test_tiers_are_stored_and_read_back():
    s = MetricsStore(":memory:")
    s.insert({"soc": 50}, 1_000_000, None, _tiers(flat=1.0))
    rows = s.tier_samples(0, 2_000_000)
    assert len(rows) == 1
    assert rows[0]["ts"] == 1_000_000
    assert rows[0]["flat"] == [1.0] * 7
    s.close()


def test_samples_without_tiers_are_skipped_not_nulls():
    s = MetricsStore(":memory:")
    s.insert({"soc": 50}, 1_000_000)                       # no tiers
    s.insert({"soc": 51}, 1_000_060, None, _tiers(peak=2.0))
    assert len(s.query(0, 2_000_000, None)) == 2           # both are real samples
    assert len(s.tier_samples(0, 2_000_000)) == 1          # only one carries tiers
    s.close()


def test_malformed_tiers_stored_as_null_not_raised():
    """A telemetry extra must never kill a poll."""
    s = MetricsStore(":memory:")
    for bad in (None, "nonsense", 42, {}, {"peak": "not-a-list"}, {"bogus": [1]}):
        s.insert({"soc": 50}, 1_000_000 + hash(str(bad)) % 1000, None, bad)
    assert s.tier_samples(0, 2_000_000) == []
    s.close()


def test_unknown_tier_keys_are_dropped():
    s = MetricsStore(":memory:")
    s.insert({"soc": 50}, 1_000_000, None,
             {"peak": [1.0] * 7, "somethingelse": [9.0]})
    row = s.tier_samples(0, 2_000_000)[0]
    assert set(row) == {"ts", "peak"}
    s.close()


def test_tier_samples_filter_by_gateway():
    s = MetricsStore(":memory:")
    s.insert({"soc": 50}, 1_000_000, "gw-a", _tiers(flat=1.0))
    s.insert({"soc": 50}, 1_000_060, "gw-b", _tiers(peak=1.0))
    assert len(s.tier_samples(0, 2_000_000, "gw-a")) == 1
    assert len(s.tier_samples(0, 2_000_000)) == 2
    s.close()


def test_tier_migration_is_idempotent_on_an_existing_db(tmp_path):
    """A pre-tier DB must gain the column without losing rows."""
    path = str(tmp_path / "m.db")
    first = MetricsStore(path)
    first.insert({"soc": 50, "grid_w": 1}, 1_000_000)
    first.close()
    second = MetricsStore(path)                    # re-open runs migrations again
    second.insert({"soc": 51}, 1_000_060, None, _tiers(valley=3.0))
    assert second.info()["count"] == 2             # original row preserved
    assert len(second.tier_samples(0, 2_000_000)) == 1
    second.close()


def test_stored_shape_feeds_tier_transitions():
    """The stored rows must be directly consumable by the library helper."""
    from franklinwh_local import energy

    s = MetricsStore(":memory:")
    s.insert({"soc": 50}, 1_000_000, None, _tiers(flat=1.0))
    s.insert({"soc": 50}, 1_000_060, None, _tiers(flat=2.0))
    s.insert({"soc": 50}, 1_000_120, None, _tiers(flat=2.0, peak=1.0))
    s.insert({"soc": 50}, 1_000_180, None, _tiers(flat=2.0, peak=2.0))
    assert energy.tier_transitions(s.tier_samples(0, 2_000_000)) == [
        (1_000_120, "flat", "peak")]
    s.close()


def test_retention_default_is_a_year():
    """365d ~= 130 MB at a 30s poll (measured 0.35 MB/day). The old 30d default was
    the only reason the gateway's ~105-day history looked like the longer record."""
    from franklinwh_local_bridge.config import Settings
    assert Settings().metrics_retention_days == 365


def test_prune_respects_the_configured_window():
    s = MetricsStore(":memory:")
    now = 1_000_000_000
    s.insert({"soc": 50}, now - 400 * 86400)       # older than a year
    s.insert({"soc": 51}, now - 100 * 86400)       # inside a year
    s.insert({"soc": 52}, now)
    assert s.prune(365, now) == 1                  # only the 400-day-old row
    assert s.info()["count"] == 2
    s.close()
