"""FEAT-GRID-PROFILE-TAB — the read-only /api/grid endpoint.

Mocks the aGate read (install_profile / 1701) + the Modbus-702 inverter ratings: the endpoint's
job is to structure them and apply the -1=unlimited convention + the 702-not-1701 kW source.
"""
from fastapi.testclient import TestClient

from franklinwh_local_bridge import (app as app_module, client as client_mod, config,
                                     environment, db, battery_control)
from franklinwh_local_bridge.db import MetricsStore

PROFILE = {
    "opt": 0, "result": 0, "reason": 0,
    "isThreePhaseInstall": 0, "airSwitchCur": 100, "ratedGridVolt": 0, "ratedGridHz": 1,
    "gridExportEnable": 1, "isPcsDischgEn": 1, "kwRatePower": -1, "gridSoftLimit": -1,
    "gridHardLimit": -1, "fhpRatePower": 0, "electricSupply": 63,
}


def _client(tmp_path, monkeypatch, ratings=(5000, 5000), profile=PROFILE):
    st = MetricsStore(str(tmp_path / "m.db"))
    monkeypatch.setattr(environment, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "_settings", None)
    monkeypatch.setattr(db, "get_store", lambda s: st)
    monkeypatch.setattr(client_mod, "read", lambda s, name, host=None: dict(profile))
    monkeypatch.setattr(battery_control, "cached_ratings", lambda host: ratings)
    return TestClient(app_module.create_app())


def test_grid_endpoint_structures_and_converts(tmp_path, monkeypatch):
    out = _client(tmp_path, monkeypatch).get("/api/grid").json()
    gc, gl, inv = out["grid_connection"], out["grid_limits"], out["inverter"]
    assert gc["three_phase"] is False and gc["service_amps"] == 100
    assert gc["electric_supply_raw"] == 63                    # kept raw, flagged in the UI
    assert gl["export_enable"] is True and gl["pcs_discharge"] is True
    assert gl["grid_soft_limit"] == -1 and gl["grid_hard_limit"] == -1   # -1 = unlimited (UI renders it)
    assert inv["max_charge_kw"] == 5.0 and inv["max_discharge_kw"] == 5.0
    assert inv["source"] == "Modbus SunSpec 702"
    assert inv["fhp_rate_power_1701"] == 0                    # the unreliable 1701 field, surfaced


def test_grid_endpoint_no_modbus(tmp_path, monkeypatch):
    out = _client(tmp_path, monkeypatch, ratings=(None, None)).get("/api/grid").json()
    assert out["inverter"]["max_charge_kw"] is None and out["inverter"]["source"] is None


# ── PCS write modal — /api/grid/limits (UNVERIFIED 1701 write) ────────────────
def _writeclient(tmp_path, monkeypatch, captured, result=None):
    st = MetricsStore(str(tmp_path / "m.db"))
    monkeypatch.setattr(environment, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "_settings", None)
    monkeypatch.setattr(db, "get_store", lambda s: st)

    def fake_set(s, changes, host=None, dry_run=False):
        captured.update(changes=dict(changes), host=host, dry_run=dry_run)
        return dict(result or {"ok": True, "requested": dict(changes),
                               "before": {}, "after": dict(changes),
                               "confirmed": True, "mismatched": {},
                               "frame": {"cmdType": 1701, "dataArea": {"opt": 1, **changes}}})
    monkeypatch.setattr(client_mod, "set_grid_limits", fake_set)
    return TestClient(app_module.create_app())


def test_grid_limits_dry_run_needs_no_confirm(tmp_path, monkeypatch):
    cap = {}
    c = _writeclient(tmp_path, monkeypatch, cap)
    out = c.post("/api/grid/limits", json={"grid_soft_limit": -1, "dry_run": True}).json()
    assert cap["dry_run"] is True and cap["changes"] == {"gridSoftLimit": -1}
    assert out["frame"]["dataArea"]["opt"] == 1


def test_grid_limits_write_requires_confirm(tmp_path, monkeypatch):
    cap = {}
    c = _writeclient(tmp_path, monkeypatch, cap)
    r = c.post("/api/grid/limits", json={"export_enable": False})
    assert r.status_code == 428 and not cap          # nothing was sent
    assert "UNVERIFIED" in r.json()["detail"]


def test_grid_limits_maps_fields_and_audits(tmp_path, monkeypatch):
    cap = {}
    c = _writeclient(tmp_path, monkeypatch, cap)
    out = c.post("/api/grid/limits",
                 json={"export_enable": False, "pcs_discharge": True,
                       "grid_hard_limit": 3.0, "confirm": True}).json()
    # booleans → 0/1, kW passthrough
    assert cap["changes"] == {"gridExportEnable": 0, "isPcsDischgEn": 1, "gridHardLimit": 3.0}
    assert out["ok"] is True
    # cloud witness present but unavailable (no creds in the test settings)
    assert out["cloud"]["available"] is False


def test_grid_limits_no_fields_400(tmp_path, monkeypatch):
    c = _writeclient(tmp_path, monkeypatch, {})
    assert c.post("/api/grid/limits", json={"confirm": True}).status_code == 400


class _FakeLibClient:
    """A library client whose install_profile() returns `before` then `after` (read-modify-read)."""
    def __init__(self, before, after, reply):
        self._reads = [before, after]
        self._reply = reply
        self.sent = None
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def login(self): pass
    def install_profile(self): return self._reads.pop(0)
    def call(self, cmd, data): self.sent = (cmd, data); return self._reply


def test_set_grid_limits_readback_confirms(tmp_path, monkeypatch):
    before = {"opt": 0, "result": 0, "gridSoftLimit": -1, "gridHardLimit": -1, "gridExportEnable": 1}
    after = {"opt": 0, "gridSoftLimit": 3, "gridHardLimit": -1, "gridExportEnable": 1}
    fake = _FakeLibClient(before, after, {"result": 0})
    monkeypatch.setattr(client_mod, "_client", lambda s, host=None: fake)
    out = client_mod.set_grid_limits(object(), {"gridSoftLimit": 3})
    assert out["ok"] is True and out["confirmed"] is True
    assert out["before"] == {"gridSoftLimit": -1} and out["after"] == {"gridSoftLimit": 3}
    assert fake.sent[0] == 1701 and fake.sent[1]["opt"] == 1 and fake.sent[1]["gridSoftLimit"] == 3
    assert "result" not in fake.sent[1]              # metadata stripped from the write block


def test_set_grid_limits_detects_silent_ignore(tmp_path, monkeypatch):
    """result:0 but the field didn't change → ok False (the silent-discard case)."""
    before = {"gridExportEnable": 1}
    after = {"gridExportEnable": 1}                   # asked to disable, device kept it on
    fake = _FakeLibClient(before, after, {"result": 0})
    monkeypatch.setattr(client_mod, "_client", lambda s, host=None: fake)
    out = client_mod.set_grid_limits(object(), {"gridExportEnable": 0})
    assert out["ok"] is False and out["confirmed"] is False
    assert out["mismatched"]["gridExportEnable"] == {"requested": 0, "actual": 1}
