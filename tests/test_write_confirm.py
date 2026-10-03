"""FEAT-WRITE-CONFIRM — the global ALLOW_WRITES gate is dropped; the physically
consequential actions (operating-mode change, off-grid) instead require an explicit
``confirm`` (HTTP 428). Reversible writes just work; the UI reports writes open."""
from fastapi.testclient import TestClient

from franklinwh_local_bridge import app as app_module, config, environment, db
from franklinwh_local_bridge.db import MetricsStore


def _client(tmp_path, monkeypatch):
    store = MetricsStore(str(tmp_path / "m.db"))
    monkeypatch.setattr(environment, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "_settings", None)
    monkeypatch.setattr(db, "get_store", lambda s: store)
    return TestClient(app_module.create_app())


def test_consequential_actions_require_confirm(tmp_path, monkeypatch):
    """Mode change / off-grid are refused without confirm — and the guard fires
    BEFORE any gateway call, so this is fast and never touches hardware."""
    c = _client(tmp_path, monkeypatch)
    assert c.post("/api/mode", json={"mode": "self"}).status_code == 428
    assert c.post("/api/offgrid", json={"on": True, "soc": 5}).status_code == 428
    assert c.post("/api/cloud/set-mode", json={"requestedOperatingMode": 2}).status_code == 428


def test_reversible_write_needs_no_confirm(tmp_path, monkeypatch):
    """A reversible config write (automation constants) just works — no gate, no confirm."""
    c = _client(tmp_path, monkeypatch)
    r = c.put("/api/constants", json={"min_discharge_soc": 22})
    assert r.status_code == 200 and r.json()["values"]["min_discharge_soc"] == 22.0


def test_settings_report_writes_open(tmp_path, monkeypatch):
    """The global gate is dropped, so the UI is told writes are open (canWrite → true)."""
    c = _client(tmp_path, monkeypatch)
    assert c.get("/api/settings").json()["control"]["allow_writes"] is True
