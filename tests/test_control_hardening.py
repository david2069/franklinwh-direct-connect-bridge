"""FEAT-CONTROL-HARDENING — control audit trail, Modbus master switch, and the
FEAT-TOPNAV-RUNSTATUS roster fields (run_status → off_grid / vpp)."""
from types import SimpleNamespace

from fastapi.testclient import TestClient

from franklinwh_local_bridge import app as app_module, config, environment, db
from franklinwh_local_bridge import battery_control
from franklinwh_local_bridge.db import MetricsStore


def _client(tmp_path, monkeypatch):
    store = MetricsStore(str(tmp_path / "m.db"))
    monkeypatch.setattr(environment, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "_settings", None)
    monkeypatch.setattr(db, "get_store", lambda s: store)
    return TestClient(app_module.create_app()), store


# ── audit trail (db) ─────────────────────────────────────────────────────────
def test_control_log_roundtrip(tmp_path):
    st = MetricsStore(str(tmp_path / "m.db"))
    st.log_control_event("go_off_grid", gateway_id="g1", detail="restore_soc=20%",
                         result="ok", ok=True, now=100.0)
    st.log_control_event("reboot_gateway", detail="restart aGate", ok=None, now=200.0)
    rows = st.control_log(limit=10)
    assert [r["action"] for r in rows] == ["reboot_gateway", "go_off_grid"]  # newest first
    assert rows[1]["ok"] == 1 and rows[1]["detail"] == "restore_soc=20%"
    assert st.control_log(action="reboot_gateway")[0]["ok"] is None


# ── Modbus master switch ─────────────────────────────────────────────────────
def test_modbus_toggle_persists_and_audits(tmp_path, monkeypatch):
    c, store = _client(tmp_path, monkeypatch)
    try:
        assert c.get("/api/modbus").json()["enabled"] is True           # default on
        assert c.put("/api/modbus", json={"enabled": False}).json()["enabled"] is False
        assert battery_control.is_enabled() is False
        assert battery_control.available()[0] is False                  # gate closed
        assert store.get_config("modbus_enabled") == "0"                # persisted
        # the toggle is recorded in the audit trail
        log = c.get("/api/control-log").json()["events"]
        assert any(e["action"] == "modbus_toggle" for e in log)
    finally:
        battery_control.set_enabled(True)   # never leak the disabled flag to other tests


# ── FEAT-TOPNAV-RUNSTATUS roster derivation ──────────────────────────────────
def _fake_gw(run_status, vpp_active=None, cloud_vpp=None, cloud_ts=None,
             cloud_programme=None):
    import time
    return SimpleNamespace(
        id="g1", label="GW", configured_host="1.2.3.4", active_host="1.2.3.4",
        serial="SN", firmware="v1", mqtt_connected=True, vpp_active=vpp_active,
        cloud_vpp=cloud_vpp, cloud_mode="", cloud_programme=cloud_programme,
        cloud_ts=(time.time() if cloud_ts is None and cloud_vpp is not None else (cloud_ts or 0)),
        last_summary={"ok": True, "power": {"soc": 50, "run_status": run_status}})


def test_roster_entry_surfaces_offgrid_and_vpp():
    off = app_module._roster_entry(_fake_gw(7))     # Off-Grid Discharging
    assert off["off_grid"] is True and off["vpp"] is False
    assert off["run_status_desc"] == "Off-Grid Discharging"
    normal = app_module._roster_entry(_fake_gw(2))  # Discharging (on-grid)
    assert normal["off_grid"] is False and normal["vpp"] is False


def test_dispatch_kind_force_vs_cloud_vpp():
    """A Modbus force with NO cloud confirmation is 'force' (honest — could be a local
    force_charge). Only the cloud can promote it to 'vpp'."""
    # run_status 2 (Discharging), Modbus force active, cloud silent → force.
    force = app_module._roster_entry(_fake_gw(2, vpp_active=True))
    assert force["vpp"] is True and force["vpp_kind"] == "force"
    assert force["run_status_desc"] == "Discharging"        # direction still honest
    # cloud confirms a VPP (fresh) → 'vpp' wins, carries the programme.
    vpp = app_module._roster_entry(_fake_gw(2, vpp_active=True, cloud_vpp=True,
                                            cloud_programme="Virtual Peakers (Ausgrid)"))
    assert vpp["vpp_kind"] == "vpp" and vpp["vpp_programme"] == "Virtual Peakers (Ausgrid)"
    # a STALE cloud VPP (old ts) is ignored → falls back to the live force signal.
    stale = app_module._roster_entry(_fake_gw(2, vpp_active=True, cloud_vpp=True, cloud_ts=1.0))
    assert stale["vpp_kind"] == "force"
    # no dispatch at all → nothing.
    assert app_module._roster_entry(_fake_gw(2))["vpp_kind"] is None


def test_cloud_programme_label_parses_strings_and_dicts():
    from franklinwh_local_bridge import cloud_status
    assert cloud_status._programme_label(["Ausgrid VPP", "  "]) == "Ausgrid VPP"
    assert cloud_status._programme_label([{"partnerName": "Amber", "programName": "P"}]) == "Amber"
    assert cloud_status._programme_label([{"programName": "Solar Sponge"}]) == "Solar Sponge"
    assert cloud_status._programme_label([]) is None
    assert cloud_status._programme_label(None) is None
