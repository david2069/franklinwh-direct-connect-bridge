"""Phase 0 tests — app wiring, no hardware (client calls are monkeypatched)."""

from fastapi.testclient import TestClient

from franklinwh_local_bridge import app as app_module
from franklinwh_local_bridge import client as client_module


def _app():
    return TestClient(app_module.create_app())


def test_index_and_docs():
    c = _app()
    assert c.get("/").status_code == 200
    assert c.get("/openapi.json").status_code == 200


def test_health_endpoint(monkeypatch):
    monkeypatch.setattr(client_module, "health",
                        lambda s, host=None: {"ok": True, "host": "10.0.0.1",
                                              "latency_ms": 12.3})
    c = _app()
    r = c.get("/api/health")
    assert r.status_code == 200 and r.json()["ok"] is True


def test_summary_endpoint(monkeypatch):
    monkeypatch.setattr(client_module, "summary",
                        lambda s, host=None: {"ok": True, "power": {"soc": 55},
                                              "mode": {"modes": []}, "latency_ms": 10.0})
    c = _app()
    r = c.get("/api/summary")
    assert r.status_code == 200 and r.json()["power"]["soc"] == 55


def test_power_endpoint(monkeypatch):
    monkeypatch.setattr(client_module, "power",
                        lambda s, host=None: {"soc": 55, "p_load": 500})
    c = _app()
    r = c.get("/api/power")
    assert r.status_code == 200 and r.json()["soc"] == 55


def test_read_endpoint_maps_transport_error_to_502(monkeypatch):
    from franklinwh_local.transport import TransportError

    def boom(s, host=None):
        raise TransportError("host is down")

    monkeypatch.setattr(client_module, "firmware", boom)
    c = _app()
    assert c.get("/api/firmware").status_code == 502


# -- gated control writes ---------------------------------------------------

def test_write_endpoints_403_when_writes_disabled(monkeypatch):
    monkeypatch.setattr(client_module, "writes_enabled", lambda s: False)
    c = _app()
    assert c.post("/api/mode", json={"mode": "self"}).status_code == 428
    assert c.post("/api/offgrid", json={"on": False}).status_code == 428


def test_set_mode_when_enabled(monkeypatch):
    monkeypatch.setattr(client_module, "writes_enabled", lambda s: True)
    monkeypatch.setattr(client_module, "set_mode",
                        lambda s, mode, host=None: {"ok": True, "result": 0,
                                                    "current_id_before": 2,
                                                    "current_id_after": 3})
    c = _app()
    r = c.post("/api/mode", json={"mode": "tou", "confirm": True})
    assert r.status_code == 200 and r.json()["ok"] is True


def test_set_offgrid_when_enabled(monkeypatch):
    monkeypatch.setattr(client_module, "writes_enabled", lambda s: True)
    monkeypatch.setattr(client_module, "set_offgrid",
                        lambda s, on, soc, host=None: {"ok": True, "result": 0})
    c = _app()
    r = c.post("/api/offgrid", json={"on": False, "confirm": True})
    assert r.status_code == 200 and r.json()["ok"] is True


def test_cloud_write_endpoints_403_when_writes_disabled(monkeypatch):
    monkeypatch.setattr(client_module, "writes_enabled", lambda s: False)
    c = _app()
    assert c.post("/api/cloud/set-mode",
                  json={"requestedOperatingMode": 2}).status_code == 428
    assert c.post("/api/cloud/grid-status",
                  json={"status": "Normal"}).status_code == 403
    assert c.post("/api/cloud/smart-circuit/state",
                  json={"circuit": 1, "turn_on": True}).status_code == 403
    assert c.post("/api/cloud/reserve",
                  json={"requestedSOC": 20}).status_code == 403


def test_cloud_set_mode_maps_workmode_and_lists_not_applied(monkeypatch):
    monkeypatch.setattr(client_module, "writes_enabled", lambda s: True)
    seen = {}

    def fake_set_mode(s, mode, host=None):
        seen["mode"] = mode
        return {"ok": True, "result": 0, "current_id_before": 1, "current_id_after": 2}

    monkeypatch.setattr(client_module, "set_mode", fake_set_mode)
    c = _app()
    # workMode 3 (Emergency Backup) → local 'backup' alias; requestedSOC provided.
    r = c.post("/api/cloud/set-mode",
               json={"requestedOperatingMode": 3, "requestedSOC": 30, "confirm": True})
    assert r.status_code == 200
    body = r.json()
    assert seen["mode"] == "backup"
    assert body["ok"] is True
    assert body["not_applied_locally"] == ["requestedSOC"]
    assert "note" in body


def test_cloud_set_mode_no_extras_has_empty_not_applied(monkeypatch):
    monkeypatch.setattr(client_module, "writes_enabled", lambda s: True)
    monkeypatch.setattr(client_module, "set_mode",
                        lambda s, mode, host=None: {"ok": True, "result": 0})
    c = _app()
    r = c.post("/api/cloud/set-mode", json={"requestedOperatingMode": "tou", "confirm": True})
    assert r.status_code == 200
    assert r.json()["not_applied_locally"] == []


def test_cloud_set_mode_uses_cloud_numbering_not_oldindex(monkeypatch):
    """Guard the TOU<->Backup trap: cloud workMode is TOU=1/Self=2/Backup=3, but the local
    API's oldIndex is Modbus-style Backup=1/Self=2/TOU=3. The facade must resolve the cloud
    workMode to a NAME (never reuse the number as a local index) or set-mode switches to the
    WRONG mode. workMode 1 MUST map to 'tou' (not 'backup')."""
    monkeypatch.setattr(client_module, "writes_enabled", lambda s: True)
    seen = {}
    monkeypatch.setattr(client_module, "set_mode",
                        lambda s, mode, host=None: seen.__setitem__("mode", mode) or {"ok": True, "result": 0})
    c = _app()
    for wm, alias in ((1, "tou"), (2, "self"), (3, "backup")):
        c.post("/api/cloud/set-mode", json={"requestedOperatingMode": wm, "confirm": True})
        assert seen["mode"] == alias, f"cloud workMode {wm} must map to {alias!r}, got {seen['mode']!r}"


def test_cloud_grid_status_normal_is_reconnect(monkeypatch):
    monkeypatch.setattr(client_module, "writes_enabled", lambda s: True)
    seen = {}

    def fake_offgrid(s, on, soc, host=None):
        seen["on"] = on
        seen["soc"] = soc
        return {"ok": True, "result": 0}

    monkeypatch.setattr(client_module, "set_offgrid", fake_offgrid)
    c = _app()
    r = c.post("/api/cloud/grid-status", json={"status": "Normal", "soc": 5})
    assert r.status_code == 200 and seen["on"] is False
    r = c.post("/api/cloud/grid-status", json={"status": "OFF", "soc": 10})
    assert r.status_code == 200 and seen["on"] is True and seen["soc"] == 10


def test_cloud_smart_circuit_state_returns_readback(monkeypatch):
    monkeypatch.setattr(client_module, "writes_enabled", lambda s: True)
    monkeypatch.setattr(client_module, "set_smart_circuit",
                        lambda s, circuit, on, host=None: {"ok": True, "result": 0,
                                                           "circuit": circuit,
                                                           "requested": 1, "before": 0,
                                                           "after": 1, "confirmed": True})
    c = _app()
    r = c.post("/api/cloud/smart-circuit/state", json={"circuit": 2, "turn_on": True})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["confirmed"] is True
    assert body["hardware_verified"] is True and "hardware_note" in body


def test_cloud_reserve_503_without_provider(monkeypatch):
    # HYBRID Phase 3: with no cloud provider configured, the reserve write reports 503
    # (503 = no provider; 501 is now reserved for the FWHAI-not-wired path).
    monkeypatch.setattr(client_module, "writes_enabled", lambda s: True)
    from franklinwh_local_bridge import providers
    import time as _t
    monkeypatch.setattr(providers, "_probe_url", lambda base, *a, **k: False)
    monkeypatch.setattr(providers, "_lib_available", lambda m: False)
    # Auth must read VALID so _require_cloud passes and we reach the no-PROVIDER branch
    # (503 "reserve"), rather than the "creds not checked" 503. Set the breaker directly
    # instead of depending on ambient/persisted state (which DATA_DIR isolation clears).
    monkeypatch.setattr(providers, "_breaker_loaded", True)
    providers._cloud_auth.update(state="valid", fail_count=0, error=None, checked_at=_t.time())
    c = _app()
    r = c.post("/api/cloud/reserve", json={"requestedSOC": 20, "workMode": 2})
    assert r.status_code == 503
    assert "reserve" in r.json()["detail"].lower()


def test_set_mode_maps_transport_error_to_502(monkeypatch):
    from franklinwh_local.transport import TransportError

    monkeypatch.setattr(client_module, "writes_enabled", lambda s: True)

    def boom(s, mode, host=None):
        raise TransportError("host is down")

    monkeypatch.setattr(client_module, "set_mode", boom)
    c = _app()
    assert c.post("/api/mode", json={"mode": "self", "confirm": True}).status_code == 502


def test_live_endpoint_no_device_io():
    """Liveness probe returns 200 with NO monkeypatching of the device client — proving
    it does no gateway I/O (so a down aGate can't mark the container unhealthy)."""
    c = _app()
    r = c.get("/api/live")
    assert r.status_code == 200
    assert r.json()["status"] == "ok" and r.json()["service"] == "franklinwh-local-bridge"


def test_summary_served_from_poller_cache_not_device(monkeypatch):
    """When the poller is caching (metrics on by default in dev), /api/summary must serve
    the cached last-good summary and NOT hit the device — this is the flicker/slow-load fix."""
    from franklinwh_local_bridge import state as state_module
    cached = {"ok": True, "power": {"soc": 77},
              "mode": {"modes": [{"name": "Self-Consumption", "active": True}]}}
    monkeypatch.setattr(state_module.get_state(), "last_summary", cached)

    def boom(s, host=None):
        raise AssertionError("client.summary must NOT be called when the cache is warm")

    monkeypatch.setattr(client_module, "summary", boom)
    c = _app()
    r = c.get("/api/summary")
    assert r.status_code == 200
    body = r.json()
    assert body["cached"] is True and body["power"]["soc"] == 77
    assert body["mode"]["modes"][0]["active"] is True


def test_summary_falls_back_to_device_when_cache_empty(monkeypatch):
    from franklinwh_local_bridge import state as state_module
    monkeypatch.setattr(state_module.get_state(), "last_summary", {})
    monkeypatch.setattr(client_module, "summary",
                        lambda s, host=None: {"ok": True, "power": {"soc": 42},
                                              "fresh": True})
    c = _app()
    r = c.get("/api/summary")
    assert r.status_code == 200 and r.json().get("fresh") is True


# ── raw cmdType console ──────────────────────────────────────────────────────
def test_raw_read_returns_request_and_response_verbatim(monkeypatch):
    """The console's value is fidelity: what was sent, and what came back."""
    sent = {}

    def fake(s, cmd, data=None, host=None):
        sent.update(cmd=cmd, data=data)
        return {"request": {"cmdType": cmd, "dataArea": data},
                "response": {"opt": 0, "result": 0, "BBBackupSoc": 20},
                "elapsed_ms": 47, "accepted": True, "is_write": False,
                "catalog": {"name": "mode_soc"}, "warning": None}

    monkeypatch.setattr(client_module, "raw_command", fake)
    r = TestClient(app_module.create_app()).post(
        "/api/raw", json={"cmd": 1405, "data": {"opt": 0}})
    assert r.status_code == 200
    body = r.json()
    assert body["request"]["dataArea"] == {"opt": 0}
    assert body["response"]["BBBackupSoc"] == 20
    assert sent["cmd"] == 1405
    # fields the Terminal console renders on each reply: "(sent <cmdType>)  <ms> ms"
    assert body["request"]["cmdType"] == 1405 and body["elapsed_ms"] == 47
    assert "response" in body and body["warning"] is None


def test_raw_write_requires_confirmation(monkeypatch):
    """A raw console is exactly where a mistyped opt becomes a reboot."""
    called = []
    monkeypatch.setattr(client_module, "writes_enabled", lambda s: True)
    monkeypatch.setattr(client_module, "raw_command",
                        lambda *a, **k: called.append(1) or {"response": {}})
    r = TestClient(app_module.create_app()).post(
        "/api/raw", json={"cmd": 1721, "data": {"opt": 1, "reboot": 1}})
    assert r.status_code == 428 and not called          # nothing was sent
    assert "WRITE" in r.json()["detail"]


def test_raw_write_names_the_hazard(monkeypatch):
    """1727 opt:3 switched the live operating mode during a probe — say so first."""
    monkeypatch.setattr(client_module, "writes_enabled", lambda s: True)
    r = TestClient(app_module.create_app()).post(
        "/api/raw", json={"cmd": 1727, "data": {"opt": 3, "current_id": 1}})
    assert "SWITCHES THE ACTIVE OPERATING MODE" in r.json()["detail"]


def test_raw_write_requires_confirm():
    # The global write-gate is gone (FEAT-WRITE-CONFIRM), but a raw WRITE (opt != the
    # command's read opt) is still refused without an explicit confirm (428).
    r = TestClient(app_module.create_app()).post(
        "/api/raw", json={"cmd": 1409, "data": {"opt": 1}})
    assert r.status_code == 428


def test_raw_catalog_lists_commands():
    body = TestClient(app_module.create_app()).get("/api/raw/catalog").json()
    assert len(body["commands"]) > 50
    assert any(c["cmd"] == 1405 for c in body["commands"])


def test_raw_read_opt_is_per_command_not_always_zero(monkeypatch):
    """1725 READS with opt:1. Treating 'opt != 0' as a write blocked that read.

    Found when the console hung on 1725 while the panel below it worked — the
    panel calls mode_list(), which sends opt:1.
    """
    seen = {}
    monkeypatch.setattr(client_module, "raw_command",
                        lambda s, cmd, data=None, host=None: seen.update(
                            cmd=cmd, data=data) or {"response": {}, "is_write": False})
    r = TestClient(app_module.create_app()).post(
        "/api/raw", json={"cmd": 1725, "data": {"opt": 1}})
    assert r.status_code == 200, "opt:1 on 1725 is a READ and must not need confirm"
    assert seen["data"] == {"opt": 1}


def test_raw_opt_zero_on_1725_is_treated_as_a_write(monkeypatch):
    """The converse: opt:0 is NOT 1725's read, so it needs the confirm gate."""
    monkeypatch.setattr(client_module, "writes_enabled", lambda s: True)
    r = TestClient(app_module.create_app()).post(
        "/api/raw", json={"cmd": 1725, "data": {"opt": 0}})
    assert r.status_code == 428
    assert "reads with opt=1" in r.json()["detail"]


def test_empty_dataarea_is_sent_verbatim_not_replaced_by_the_default(monkeypatch):
    """`data or default` treated {} as missing — choosing "no opt" sent {"opt":1}.

    An EMPTY dataArea is a deliberate choice (1725 with no opt is refused
    result:1 reason:-2, which is diagnostically different from opt:0's silence),
    so it must reach the wire exactly as typed.
    """
    seen = {}
    monkeypatch.setattr(client_module, "writes_enabled", lambda s: True)
    monkeypatch.setattr(client_module, "raw_command",
                        lambda s, cmd, data=None, host=None: seen.update(data=data)
                        or {"response": {}, "is_write": True})
    TestClient(app_module.create_app()).post(
        "/api/raw", json={"cmd": 1725, "data": {}, "confirm": True})
    assert seen["data"] == {}, "an explicitly empty dataArea must not be substituted"


def test_omitted_dataarea_falls_back_to_the_read_payload(monkeypatch):
    """The converse: no data at all SHOULD use the command's read payload."""
    seen = {}
    monkeypatch.setattr(client_module, "raw_command",
                        lambda s, cmd, data=None, host=None: seen.update(data=data)
                        or {"response": {}, "is_write": False})
    TestClient(app_module.create_app()).post("/api/raw", json={"cmd": 1725})
    assert seen["data"] is None      # client passes through; raw_command defaults


def test_index_is_never_cached():
    """The HTML carries the hashed asset URLs, so a cached page pins the browser to
    stale JS however good the asset hashing is — which made three consecutive fixes
    appear absent until a hard refresh."""
    r = TestClient(app_module.create_app()).get("/")
    assert "no-store" in r.headers.get("cache-control", "")


def test_version_endpoint_reports_the_asset_token():
    body = TestClient(app_module.create_app()).get("/api/version").json()
    assert "version" in body and body.get("asset")


def test_ui_offers_a_reload_when_the_build_changes():
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1] / "src/franklinwh_local_bridge"
    js = (root / "static/js/app.js").read_text()
    assert "checkBuild" in js and "newBuild" in js
    assert "api/version" in js
    # The rebuild notice is a styled permission modal (index.html), not a topbar
    # badge — it asks before reloading and can be dismissed with "Later".
    index = (root / "templates/index.html").read_text()
    assert "New-build available modal" in index
    assert "reloadForBuild" in index and "dismissBuild" in index


def test_reboot_button_exists_and_is_gated():
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1] / "src/franklinwh_local_bridge"
    html = (root / "templates/tabs/control.html").read_text()
    assert "rebootGateway()" in html
    assert "writes_enabled" in html.split("Gateway</div>")[1][:900]
    js = (root / "static/js/app.js").read_text()
    body = js[js.index("async rebootGateway()"):]
    assert "confirmDialog" in body[:700], "reboot must confirm first"
    assert "confirm: true" in body[:1400], "the endpoint requires confirm=true"


def test_reboot_requires_confirm_flag():
    r = TestClient(app_module.create_app()).post("/api/reboot", json={"confirm": False})
    assert r.status_code in (400, 403)


def test_mode_field_is_not_labelled_tou():
    """The 1301 `mode`/`name` fields are the OPERATING (work) mode, not TOU — the
    Device-tab labels must say so (user-reported mislabel)."""
    from franklinwh_local_bridge import fieldschema
    import pathlib
    labels = fieldschema.FIELD_LABELS if hasattr(fieldschema, "FIELD_LABELS") else None
    src = (pathlib.Path(fieldschema.__file__)).read_text()
    assert '"tou_mode":                 "Operating Mode"' in src
    assert "TOU mode" not in src.split("FIELD_ATTRS", 1)[-1] if "FIELD_ATTRS" in src else True
