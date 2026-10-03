"""FEAT-NOTIFY — the configurable notification trigger engine + delivery log."""
from fastapi.testclient import TestClient

from franklinwh_local_bridge import notify_engine, ha_instances
from franklinwh_local_bridge import app as app_module, config, environment, db
from franklinwh_local_bridge.db import MetricsStore


def _snap(ok=True, off_grid=False, soc=50):
    return {"ok": ok, "power": {"off_grid": off_grid, "soc": soc}}


# ── evaluate (pure transitions, gated by config) ─────────────────────────────
def test_evaluate_fires_on_transitions_only():
    cfg = notify_engine.config(None)
    assert notify_engine.evaluate("GW", _snap(), None, cfg) == []          # first pass: nothing
    assert notify_engine.evaluate("GW", _snap(ok=True), _snap(ok=True), cfg) == []  # no change
    offline = notify_engine.evaluate("GW", _snap(ok=False), _snap(ok=True), cfg)
    assert offline and offline[0][0] == "aGate_offline" and "UNREACHABLE" in offline[0][2]
    offgrid = notify_engine.evaluate("GW", _snap(off_grid=True), _snap(off_grid=False), cfg)
    assert offgrid and offgrid[0][0] == "off_grid" and "OFF-GRID" in offgrid[0][2]


def test_evaluate_soc_thresholds_and_gating():
    cfg = notify_engine.config(None)
    cfg["triggers"]["soc_low"]["enabled"] = True
    cfg["triggers"]["soc_low"]["threshold"] = 20
    assert notify_engine.evaluate("", _snap(soc=18), _snap(soc=25), cfg)[0][0] == "soc_low"
    assert notify_engine.evaluate("", _snap(soc=25), _snap(soc=18), cfg) == []   # rising: no fire
    # master off silences everything
    cfg["master"] = False
    assert notify_engine.evaluate("", _snap(ok=False), _snap(ok=True), cfg) == []


# ── config persistence ────────────────────────────────────────────────────────
def test_config_roundtrip_and_threshold_clamp(tmp_path):
    st = MetricsStore(str(tmp_path / "m.db"))
    assert notify_engine.config(st)["triggers"]["off_grid"]["enabled"] is True
    notify_engine.set_config(st, {"master": False,
                                  "triggers": {"soc_low": {"enabled": True, "threshold": 250}}})
    cfg = notify_engine.config(st)
    assert cfg["master"] is False
    assert cfg["triggers"]["soc_low"]["enabled"] is True
    assert cfg["triggers"]["soc_low"]["threshold"] == 100        # clamped 0..100


# ── fire: delivery to devices + log + stats ──────────────────────────────────
def test_fire_logs_per_device_and_respects_enable(tmp_path, monkeypatch):
    st = MetricsStore(str(tmp_path / "m.db"))
    st.create_ha_instance(ha_id="ha1", name="Home", base_url="http://ha", token="t")
    st.create_notify_device(dev_id="d1", alias="Phone", instance_id="ha1", service="notify.mobile")
    monkeypatch.setattr(ha_instances, "send_notification", lambda *a, **k: {"ok": True})

    sent = notify_engine.fire(st, "off_grid", "T", "M")
    assert sent == 1
    log = st.notify_log()
    assert log[0]["event"] == "off_grid" and log[0]["device"] == "Phone" and log[0]["ok"] == 1
    stats = st.notify_stats()
    assert any(s["event"] == "off_grid" and s["count"] == 1 and s["delivered"] == 1 for s in stats)

    # a disabled trigger delivers nothing
    notify_engine.set_config(st, {"triggers": {"off_grid": {"enabled": False}}})
    assert notify_engine.fire(st, "off_grid", "T", "M") == 0


# ── API ──────────────────────────────────────────────────────────────────────
def test_notify_triggers_api(tmp_path, monkeypatch):
    store = MetricsStore(str(tmp_path / "m.db"))
    monkeypatch.setattr(environment, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "_settings", None)
    monkeypatch.setattr(db, "get_store", lambda s: store)
    c = TestClient(app_module.create_app())
    r = c.get("/api/notify/triggers").json()
    assert r["config"]["triggers"]["off_grid"]["enabled"] is True and r["stats"] == []
    put = c.put("/api/notify/triggers", json={"triggers": {"soc_low": {"enabled": True, "threshold": 15}}})
    assert put.json()["config"]["triggers"]["soc_low"]["threshold"] == 15
    assert c.get("/api/notify/log").json()["events"] == []
