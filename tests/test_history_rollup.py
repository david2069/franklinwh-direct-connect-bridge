"""#540 follow-up (owner, 2026-11-09): Local history keeps full resolution for the last
10 days, then one 5-minute row per gateway (mean, with min, max and count), like Home
Assistant's statistics. And the storage card counts the -wal/-shm files and each table."""
import json
import logging

from franklinwh_direct_connect_bridge import db as db_module
from franklinwh_direct_connect_bridge.db import MetricsStore

DAY = 86400
NOW = 1_800_000_000 - (1_800_000_000 % 300)          # on a 5-minute boundary


def _row(soc, solar, mode="Self", tiers=None, volt=None):
    return {"soc": soc, "grid_w": 0, "solar_w": solar, "battery_w": -solar, "load_w": 100,
            "generator_w": 0, "grid_voltage_v": volt, "mode": mode}


def _seed(s, start, n, gw="g1", step=30):
    for i in range(n):
        s.insert(_row(50 + i, i * 10, mode="TOU" if i == n - 1 else "Self",
                      volt=None if i % 2 else 240.0),
                 start + i * step, gateway_id=gw,
                 tiers={"peak": [i, 0], "flat": [0, 0]})


def test_old_samples_become_one_5_minute_row_with_mean_min_max_and_count():
    s = MetricsStore(":memory:")
    old = NOW - 20 * DAY
    _seed(s, old, 20)                                   # 10 minutes of 30 s samples
    _seed(s, NOW - DAY, 20)                             # recent: untouched
    done = s.roll_up(NOW)
    assert done == {"samples": 20, "rows": 2}
    rows = s.raw(old, old + 600, gateway="g1")
    assert [r["ts"] for r in rows] == [old, old + 300]
    first = rows[0]
    assert first["soc"] == sum(50 + i for i in range(10)) / 10
    assert first["solar_w"] == sum(i * 10 for i in range(10)) / 10
    assert first["grid_voltage_v"] == 240.0             # NULLs are not averaged as zero
    span = first["span"]
    assert span["n"] == 10 and span["max"]["solar_w"] == 90 and span["min"]["solar_w"] == 0
    assert rows[1]["mode"] == "TOU"                     # the bucket's last mode
    last_tiers = s.tier_samples(old, old + 600, gateway="g1")
    assert [t["peak"][0] for t in last_tiers] == [9, 19]          # each bucket's last counter
    assert len(s.raw(NOW - DAY, NOW, gateway="g1")) == 20         # full resolution kept


def test_rolling_up_twice_changes_nothing_and_gateways_stay_apart():
    s = MetricsStore(":memory:")
    old = NOW - 15 * DAY
    _seed(s, old, 10, gw="g1")
    _seed(s, old, 10, gw="g2")
    assert s.roll_up(NOW)["rows"] == 2
    assert s.roll_up(NOW) == {"samples": 0, "rows": 0}
    assert len(s.raw(old, old + 300, gateway="g2")) == 1


def test_energy_over_a_rolled_up_hour_is_unchanged():
    s = MetricsStore(":memory:")
    old = NOW - 12 * DAY
    _seed(s, old, 120)                                   # one hour
    before = s.query(old, old + 3600, 300, gateway="g1")
    s.roll_up(NOW)
    after = s.query(old, old + 3600, 300, gateway="g1")
    assert [r["solar_w"] for r in after] == [r["solar_w"] for r in before]


def test_a_window_older_than_ten_days_is_never_read_finer_than_5_minutes():
    assert db_module.history_bucket(NOW - 20 * DAY, 60, now=NOW) == 300
    assert db_module.history_bucket(NOW - 2 * DAY, 60, now=NOW) == 60
    assert db_module.history_bucket(NOW - 20 * DAY, 900, now=NOW) == 900


def test_maintenance_logs_what_it_did(caplog):
    s = MetricsStore(":memory:")
    _seed(s, NOW - 20 * DAY, 20)
    _seed(s, NOW - 400 * DAY, 2)
    with caplog.at_level(logging.INFO, logger="franklinwh_direct_connect_bridge.db"):
        db_module.history_maintenance(s, 365, now=NOW)
    text = caplog.text
    assert "Local history: 20 samples older than 10 days kept as 2 five-minute rows" in text
    assert "deleted 2 rows older than 365 days" in text           # deleted first


def test_storage_counts_the_wal_and_shm_files_and_each_table(tmp_path):
    s = MetricsStore(str(tmp_path / "m.db"))
    _seed(s, NOW - DAY, 5)
    st = s.storage_stats()
    assert "wal_bytes" in st and "shm_bytes" in st
    assert st["total_bytes"] >= st["db_bytes"]
    metrics = next(t for t in st["tables"] if t["name"] == "metrics")
    assert "bytes" in metrics                       # None where SQLite has no dbstat


def test_raw_rows_say_nothing_about_a_span():
    s = MetricsStore(":memory:")
    _seed(s, NOW - DAY, 2)
    assert s.raw(NOW - DAY, NOW, gateway="g1")[0]["span"] is None
    json.dumps(s.raw(NOW - DAY, NOW, gateway="g1"))            # export-safe


def test_storage_card_shows_the_files_and_each_tables_size(tmp_path, monkeypatch):
    from pathlib import Path
    from fastapi.testclient import TestClient
    from franklinwh_direct_connect_bridge import app as app_module, config, environment
    root = Path(app_module.__file__).parent
    html = (root / "templates" / "tabs" / "settings.html").read_text()
    card = html[html.index(">Database storage<"):][:3500]
    assert "admin.storage.total_human" in card and "admin.storage.wal_human" in card
    assert "t.bytes_human" in card and ">Size<" in card
    hist = html[html.index("<!-- ══ Metrics / history ══ -->"):][:7000]
    assert "full_resolution_days" in hist
    monkeypatch.setattr(environment, "DATA_DIR", str(tmp_path))
    config._settings = None
    db_module.reset_store()
    try:
        body = TestClient(app_module.create_app()).get("/api/admin/storage").json()
        for k in ("total_human", "wal_human", "shm_human"):
            assert k in body
        assert all("bytes_human" in t for t in body["tables"])
    finally:
        config._settings = None
        db_module.reset_store()


def test_growth_is_measured_from_this_database():
    # The fixed 0.35-0.7 MB a day predates the per-poll JSON (about 4 KB a row); the card
    # now shows what this database actually uses.
    s = MetricsStore(":memory:")
    for i in range(120):                               # one hour at 30 s, one gateway
        s.insert(_row(50, 100), NOW - 3600 + i * 30, gateway_id="g1",
                 poll={"x%d" % k: k for k in range(200)})
    g = s.growth(NOW)
    assert g["gateways"] == 1 and g["measured"] is True
    assert 2000 < g["rows_per_day"] < 4000                        # ~2880 at a 30 s poll
    assert g["recent_mb_day"] > 1                                 # the JSON dominates
    assert 0 < g["older_mb_day"] < g["recent_mb_day"] / 3
