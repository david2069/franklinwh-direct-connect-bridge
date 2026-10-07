"""OPS-ADMIN — storage insight + backup / restore / vacuum + metrics export."""
import time

from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import app as app_module, config, environment, db
from franklinwh_direct_connect_bridge.db import MetricsStore


def _client(tmp_path, monkeypatch):
    store = MetricsStore(str(tmp_path / "m.db"))
    # seed a few power samples so storage + export have content
    now = int(time.time())
    for i in range(5):
        store.insert({"soc": 50 + i, "grid_w": 100, "solar_w": 0,
                                    "battery_w": -100, "load_w": 200, "generator_w": 0,
                                    "mode": "Self-Consumption"}, now - i * 60, gateway_id="gw1")
    monkeypatch.setattr(environment, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "_settings", None)
    monkeypatch.setattr(db, "get_store", lambda s: store)
    return TestClient(app_module.create_app()), store


# ── db layer ─────────────────────────────────────────────────────────────────
def test_storage_backup_restore_vacuum(tmp_path):
    st = MetricsStore(str(tmp_path / "m.db"))
    now = int(time.time())
    for i in range(10):
        st.insert({"soc": 40, "grid_w": 0}, now - i * 60, gateway_id="g")
    stats = st.storage_stats()
    assert stats["db_bytes"] > 0
    names = {t["name"]: t for t in stats["tables"]}
    assert names["metrics"]["rows"] == 10 and names["metrics"]["span_days"] is not None

    bpath = str(tmp_path / "snap.db")
    size = st.backup_to(bpath)
    assert size > 0

    # mutate, then restore → the extra rows are gone
    st.insert({"soc": 99}, now + 1, gateway_id="g")
    assert st.storage_stats()["tables"][0]["rows"] == 11
    st.restore_from(bpath)
    assert next(t for t in st.storage_stats()["tables"] if t["name"] == "metrics")["rows"] == 10
    assert st.vacuum() > 0


# ── API ──────────────────────────────────────────────────────────────────────
def test_admin_storage_endpoint(tmp_path, monkeypatch):
    c, _ = _client(tmp_path, monkeypatch)
    r = c.get("/api/admin/storage").json()
    assert r["db_bytes"] > 0 and r["db_human"].endswith(("B", "KB", "MB"))
    assert any(t["name"] == "metrics" and t["rows"] == 5 for t in r["tables"])
    assert r["backups"] == []


def test_admin_backup_lifecycle_and_restore_gate(tmp_path, monkeypatch):
    c, _ = _client(tmp_path, monkeypatch)
    created = c.post("/api/admin/backup").json()
    assert created["ok"] and created["name"].startswith("fwh-backup-")
    name = created["name"]
    assert any(b["name"] == name for b in c.get("/api/admin/backups").json()["backups"])
    # download streams the file
    assert c.get(f"/api/admin/backup/{name}").status_code == 200
    # restore is confirm-gated (428) then succeeds
    assert c.post(f"/api/admin/backup/{name}/restore", json={}).status_code == 428
    assert c.post(f"/api/admin/backup/{name}/restore", json={"confirm": True}).json()["ok"]
    # delete
    assert c.request("DELETE", f"/api/admin/backup/{name}").json()["ok"]
    assert c.get("/api/admin/backups").json()["backups"] == []


def test_admin_backup_name_rejects_traversal(tmp_path, monkeypatch):
    c, _ = _client(tmp_path, monkeypatch)
    assert c.get("/api/admin/backup/..%2F..%2Fetc%2Fpasswd").status_code in (400, 404)
    assert c.get("/api/admin/backup/evil.db").status_code == 400


def test_admin_metrics_export_csv_and_json(tmp_path, monkeypatch):
    c, _ = _client(tmp_path, monkeypatch)
    csv = c.get("/api/admin/metrics/export?fmt=csv&hours=24")
    assert csv.status_code == 200 and "text/csv" in csv.headers["content-type"]
    lines = csv.text.strip().splitlines()
    assert lines[0].startswith("ts,soc,grid_w") and len(lines) == 6   # header + 5 rows
    js = c.get("/api/admin/metrics/export?fmt=json&hours=24").json()
    assert js["count"] == 5
