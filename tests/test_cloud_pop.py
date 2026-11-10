"""FEAT-CLOUD-POP-METRICS — CloudFront PoP edge capture + aggregation.

The franklinwh-cloud EdgeTracker snapshot shape (verified against the real library):
current_pop, total_cf_requests, cache_hits, cache_misses, last_cf_trace_id. We persist one
sample per poll and aggregate; these tests use synthetic snapshots (no cloud creds needed).
"""
from franklinwh_direct_connect_bridge import cloud_pop
from franklinwh_direct_connect_bridge.db import MetricsStore


def _snap(pop, req=2, hits=1, misses=1):
    return {"current_pop": pop, "total_cf_requests": req, "cache_hits": hits,
            "cache_misses": misses, "last_cf_trace_id": "trace=="}


def test_ingest_and_summary_aggregates_and_detects_transitions(tmp_path):
    st = MetricsStore(str(tmp_path / "m.db"))
    for pop in ["SYD62-P1", "SYD62-P1", "SYD62-P2", "MEL51-P2"]:   # edge re-homes over polls
        cloud_pop.ingest(st, _snap(pop))
    s = cloud_pop.summary(st)
    assert s["configured"] and s["samples"] == 4
    assert s["current_pop"] == "MEL51-P2"
    assert s["distribution"]["SYD62-P1"] == 4          # 2 polls × 2 requests
    assert s["distribution"]["SYD62-P2"] == 2
    assert s["total_requests"] == 8
    assert s["transition_count"] == 2                  # P1→P2, P2→MEL51
    assert s["transitions"][0]["to"] == "MEL51-P2"     # newest first
    assert s["cache_hit_rate"] == 50.0                 # 4 hits / 8 cache-classified


def test_ingest_ignores_empty_or_popless(tmp_path):
    st = MetricsStore(str(tmp_path / "m.db"))
    cloud_pop.ingest(st, None)
    cloud_pop.ingest(st, {"current_pop": None})
    cloud_pop.ingest(st, {})
    assert cloud_pop.summary(st)["samples"] == 0


def test_summary_empty_store():
    assert cloud_pop.summary(None) == {"configured": False}


def test_record_cloud_pop_row_cap(tmp_path):
    st = MetricsStore(str(tmp_path / "m.db"))
    for i in range(10):
        st.record_cloud_pop(pop=f"POP-{i}", requests=1, max_rows=3)   # cap at 3 rows
    rows = st.cloud_pop_samples()
    assert len(rows) == 3 and rows[-1]["pop"] == "POP-9"              # newest kept
