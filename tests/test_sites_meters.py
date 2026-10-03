"""Sites + Meters roster (Phase 1 of the multi-site model). DB layer + default seeding
+ gateway attachment. No live gateway needed."""
from franklinwh_local_bridge.db import MetricsStore


def _store(tmp_path):
    return MetricsStore(str(tmp_path / "m.db"))


def test_default_site_meter_seeded_and_gateways_attached(tmp_path):
    st = _store(tmp_path)
    st.seed_gateways([("192.168.0.110", "aGate"), ("192.168.0.111", "aGate 2")])
    made = st.ensure_default_site_meter()
    assert made == {"site": True, "meter": True, "attached": 2}
    sites, meters = st.sites(), st.meters()
    assert len(sites) == 1 and sites[0]["name"] == "Home" and sites[0]["is_default"]
    assert len(meters) == 1 and meters[0]["ac_type"] == "single" and meters[0]["is_default"]
    assert meters[0]["site_id"] == sites[0]["id"]
    assert all(g["meter_id"] == meters[0]["id"] for g in st.gateways())
    # idempotent
    assert st.ensure_default_site_meter() == {"site": False, "meter": False, "attached": 0}


def test_meter_crud_and_ac_type(tmp_path):
    st = _store(tmp_path)
    site = st.create_site(sid="s1", name="Home", is_default=True)
    m = st.create_meter(mid="m1", site_id="s1", name="Meter 1", ac_type="three", rated_amps=100)
    assert m["ac_type"] == "three" and m["rated_amps"] == 100.0
    st.update_meter("m1", ac_type="split", meter_number="NMI42")
    assert st.meter("m1")["ac_type"] == "split" and st.meter("m1")["meter_number"] == "NMI42"
    assert st.delete_meter("m1") is True and st.meter("m1") is None


def test_default_is_exclusive_per_scope(tmp_path):
    st = _store(tmp_path)
    st.create_site(sid="s1", name="A", is_default=True)
    st.create_site(sid="s2", name="B", is_default=True)          # flips A off
    assert [s["id"] for s in st.sites() if s["is_default"]] == ["s2"]
    # meter default is per-site
    st.create_meter(mid="m1", site_id="s1", is_default=True)
    st.create_meter(mid="m2", site_id="s1", is_default=True)     # flips m1 off (same site)
    st.create_meter(mid="m3", site_id="s2", is_default=True)     # different site, independent
    defs = {m["id"] for m in st.meters() if m["is_default"]}
    assert defs == {"m2", "m3"}


def test_gateway_meter_reassignment(tmp_path):
    st = _store(tmp_path)
    st.seed_gateways([("h", "gw")]); st.ensure_default_site_meter()
    st.create_meter(mid="m2", site_id=st.sites()[0]["id"], name="Meter 2")
    gid = st.gateways()[0]["id"]
    st.update_gateway(gid, meter_id="m2")
    assert st.gateway(gid)["meter_id"] == "m2"


def test_service_details_fields_persist(tmp_path):
    """FEAT-MODBUS-SITE-TARIFF — PTO reference/status + timezone on the meter, export note
    on the utility, all persist through create + update."""
    st = _store(tmp_path)
    sid = st.create_site(sid="s1", name="Home")["id"]
    m = st.create_meter(mid="m1", site_id=sid, name="Main", meter_number="NMI123",
                        rated_amps=100, pto_status="approved", pto_reference="EA-2024-99",
                        timezone="Australia/Sydney")
    assert m["pto_status"] == "approved" and m["pto_reference"] == "EA-2024-99"
    assert m["timezone"] == "Australia/Sydney"
    st.update_meter("m1", pto_status="pending", pto_reference="EA-2025-01")
    m2 = st.meter("m1")
    assert m2["pto_status"] == "pending" and m2["pto_reference"] == "EA-2025-01"

    u = st.create_utility(uid="u1", name="AGL", network_dnsp="Ausgrid",
                          export_note="5 kW export limit per phase")
    assert u["export_note"] == "5 kW export limit per phase"
    st.update_utility("u1", export_note="zero-export approved")
    assert st.utility("u1")["export_note"] == "zero-export approved"


def test_service_columns_migrate_onto_old_db(tmp_path):
    """The new columns are added idempotently to a pre-existing meters/utilities schema."""
    import sqlite3
    p = str(tmp_path / "old.db")
    c = sqlite3.connect(p)
    c.execute("CREATE TABLE meters(id TEXT PRIMARY KEY, site_id TEXT, name TEXT, pto_status TEXT)")
    c.execute("CREATE TABLE utilities(id TEXT PRIMARY KEY, name TEXT)")
    c.commit(); c.close()
    st = MetricsStore(p)   # __init__ runs the migrations
    mcols = [r[1] for r in st._conn.execute("PRAGMA table_info(meters)")]
    ucols = [r[1] for r in st._conn.execute("PRAGMA table_info(utilities)")]
    assert "pto_reference" in mcols and "export_note" in ucols


def test_utility_effective_dates_persist(tmp_path):
    """FEAT-UTILITY-DATES — provider (retailer) tenure dates persist through create + update
    (supersede-don't-delete on an AU/NZ retailer switch)."""
    st = _store(tmp_path)
    u = st.create_utility(uid="u1", name="AGL", effective_start="2026-09-09")
    assert u["effective_start"] == "2026-09-09" and u["effective_end"] is None
    st.update_utility("u1", effective_end="2026-12-31")
    u2 = st.utility("u1")
    assert u2["effective_start"] == "2026-09-09" and u2["effective_end"] == "2026-12-31"
