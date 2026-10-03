"""BMS recording sessions — storage, recorder thread, and the REST surface."""

import time

import pytest
from fastapi.testclient import TestClient

from franklinwh_local_bridge import app as app_module, config, environment
from franklinwh_local_bridge import bms_record, db
from franklinwh_local_bridge.bms_record import Recorder
from franklinwh_local_bridge.db import MetricsStore


def cells(v=3300, t=20.0, soc=50.0):
    return {"batVolt": [v] * 16, "batTemp": [t] * 16, "batSoc": soc,
            "batSoh": 94.9, "batTotalVolt": 53.0, "currGrp": -4.0}


# -- storage -----------------------------------------------------------------
def test_session_roundtrip_parses_cell_arrays():
    s = MetricsStore(":memory:")
    sid = s.start_bms_session(apower_sn="SN1", interval_s=15, planned=20)
    for i in range(3):
        s.add_bms_sample(sid, cells(3300 + i, 20.0 + i, 50 + i), ts=1000 + i * 15)
    s.end_bms_session(sid, now=1045)
    d = s.bms_session(sid)
    assert len(d["samples"]) == 3
    assert d["samples"][0]["volts"] == [3300] * 16      # JSON -> list
    assert d["samples"][2]["soc"] == 52.0
    assert d["ended_ts"] == 1045
    s.close()


def test_session_list_reports_real_counts_and_span():
    """`planned` is what was asked for; the count/span must be what actually landed."""
    s = MetricsStore(":memory:")
    sid = s.start_bms_session(apower_sn="SN1", interval_s=15, planned=20)
    for i in range(4):
        s.add_bms_sample(sid, cells(), ts=2000 + i * 15)
    row = s.bms_sessions()[0]
    assert row["planned"] == 20 and row["samples"] == 4
    assert row["last_ts"] - row["first_ts"] == 45
    s.close()


def test_sessions_filter_by_apower():
    s = MetricsStore(":memory:")
    a = s.start_bms_session(apower_sn="A"); s.add_bms_sample(a, cells())
    b = s.start_bms_session(apower_sn="B"); s.add_bms_sample(b, cells())
    assert len(s.bms_sessions(apower_sn="A")) == 1
    assert len(s.bms_sessions()) == 2
    s.close()


def test_delete_removes_samples_too():
    s = MetricsStore(":memory:")
    sid = s.start_bms_session(apower_sn="SN1")
    for _ in range(5):
        s.add_bms_sample(sid, cells())
    assert s.delete_bms_session(sid) == 1
    assert s.bms_session(sid) is None
    left = s._conn.execute("SELECT COUNT(*) FROM bms_samples").fetchone()[0]
    assert left == 0, "orphaned samples left behind"
    s.close()


def test_sample_without_cell_arrays_stores_null_not_crash():
    s = MetricsStore(":memory:")
    sid = s.start_bms_session()
    s.add_bms_sample(sid, {"batSoc": 50.0})           # no arrays at all
    s.add_bms_sample(sid, {"batVolt": "nonsense"})    # wrong type
    got = s.bms_session(sid)["samples"]
    assert got[0]["volts"] is None and got[1]["volts"] is None
    s.close()


def test_bms_migration_is_idempotent(tmp_path):
    path = str(tmp_path / "m.db")
    first = MetricsStore(path)
    sid = first.start_bms_session(apower_sn="SN1")
    first.add_bms_sample(sid, cells())
    first.close()
    second = MetricsStore(path)                        # re-open re-runs migrations
    assert len(second.bms_sessions()) == 1             # nothing lost
    second.close()


# -- recorder ----------------------------------------------------------------
def test_recorder_captures_and_closes():
    s, r = MetricsStore(":memory:"), Recorder()
    r.start(s, lambda: cells(), samples=3, interval_s=5, apower_sn="SN1")
    while r.status()["active"]:
        time.sleep(0.05)
    st = r.status()
    assert st["captured"] == 3 and st["errors"] == 0
    assert s.bms_session(st["session_id"])["ended_ts"] is not None
    s.close()


def test_a_dropped_read_does_not_abort_the_session():
    """This link drops routinely; a partial session is still useful."""
    s, r = MetricsStore(":memory:"), Recorder()
    n = {"i": 0}

    def flaky():
        n["i"] += 1
        if n["i"] == 2:
            raise TimeoutError("dropped")
        return cells()

    r.start(s, flaky, samples=4, interval_s=5, apower_sn="SN1")
    while r.status()["active"]:
        time.sleep(0.05)
    st = r.status()
    assert st["captured"] == 3 and st["errors"] == 1
    assert "dropped" in st["last_error"]
    s.close()


def test_stop_ends_the_session_early():
    s, r = MetricsStore(":memory:"), Recorder()
    r.start(s, lambda: cells(), samples=100, interval_s=5, apower_sn="SN1")
    time.sleep(0.1)
    r.stop()
    while r.status()["active"]:
        time.sleep(0.05)
    assert r.status()["captured"] < 100
    s.close()


def test_only_one_session_at_a_time():
    """Two concurrent recorders would double the device session rate."""
    s, r = MetricsStore(":memory:"), Recorder()
    r.start(s, lambda: cells(), samples=50, interval_s=5)
    with pytest.raises(ValueError, match="already running"):
        r.start(s, lambda: cells(), samples=5, interval_s=5)
    r.stop()
    while r.status()["active"]:
        time.sleep(0.05)
    s.close()


@pytest.mark.parametrize("kw,msg", [
    ({"samples": 20, "interval_s": 1}, "interval"),
    ({"samples": 0, "interval_s": 15}, "samples"),
    ({"samples": 99999, "interval_s": 15}, "samples"),
])
def test_recorder_guardrails(kw, msg):
    s, r = MetricsStore(":memory:"), Recorder()
    with pytest.raises(ValueError, match=msg):
        r.start(s, lambda: cells(), **kw)
    s.close()


# -- REST --------------------------------------------------------------------
@pytest.fixture
def api(tmp_path, monkeypatch):
    """Patch get_store to a tmp DB — the default metrics_db is the container's
    /data, which is read-only on the host (matches tests/test_metrics.py)."""
    store = MetricsStore(str(tmp_path / "m.db"))
    monkeypatch.setattr(environment, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "_settings", None)
    monkeypatch.setattr(db, "get_store", lambda s: store)
    bms_record._recorder = Recorder()
    yield TestClient(app_module.create_app())
    store.close()
    config._settings = None


def test_sessions_endpoint_empty(api):
    r = api.get("/api/battery/sessions")
    assert r.status_code == 200 and r.json()["sessions"] == []


def test_sessions_endpoint_lists_and_deletes(api):
    """End-to-end through the API, not just the store."""
    import franklinwh_local_bridge.db as _db
    store = _db.get_store(None)
    sid = store.start_bms_session(apower_sn="SN1", interval_s=15, planned=3)
    for i in range(3):
        store.add_bms_sample(sid, cells(3300 + i), ts=5000 + i * 15)
    store.end_bms_session(sid, now=5045)

    rows = api.get("/api/battery/sessions").json()["sessions"]
    assert len(rows) == 1 and rows[0]["samples"] == 3

    one = api.get(f"/api/battery/sessions/{sid}").json()
    assert len(one["samples"]) == 3
    assert one["samples"][0]["volts"] == [3300] * 16

    assert api.delete(f"/api/battery/sessions/{sid}").status_code == 200
    assert api.get("/api/battery/sessions").json()["sessions"] == []


def test_record_rejects_bad_parameters(api):
    assert api.post("/api/battery/record",
                    json={"samples": 20, "interval_s": 1}).status_code == 422
    assert api.post("/api/battery/record",
                    json={"samples": 9999, "interval_s": 15}).status_code == 422


def test_missing_session_is_404(api):
    assert api.get("/api/battery/sessions/999").status_code == 404
    assert api.delete("/api/battery/sessions/999").status_code == 404


def test_status_endpoint_reports_idle(api):
    assert api.get("/api/battery/record/status").json()["active"] is False


def test_stop_is_safe_when_nothing_is_running(api):
    assert api.post("/api/battery/record/stop").status_code == 200


def test_endpoints_are_documented(api):
    paths = api.get("/openapi.json").json()["paths"]
    for p in ("/api/battery/record", "/api/battery/record/stop",
              "/api/battery/record/status", "/api/battery/sessions",
              "/api/battery/sessions/{session_id}"):
        assert p in paths, p
