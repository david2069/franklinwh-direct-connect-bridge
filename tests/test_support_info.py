"""Support bundle: correct model mapping + REDACTION (no serials/host/PII leak)."""

from fastapi.testclient import TestClient

from franklinwh_local_bridge import app as app_module, client as client_module, state


def test_support_info_maps_model_and_redacts_serials(monkeypatch):
    # A fake real gateway
    gw = state.GatewayState(id="gw1", configured_host="192.168.0.110",
                            serial="10060006A02F24170091", is_mock=False)
    monkeypatch.setattr(app_module, "get_gateways", lambda: [gw], raising=False)
    monkeypatch.setattr("franklinwh_local_bridge.state.gateways", lambda: [gw])
    # firmware carries serials + SyHdVersion — the endpoint must map the model but drop serials
    monkeypatch.setattr(client_module, "firmware", lambda s, host=None: {
        "SyHdVersion": 102, "protocolVer": "V1.11.03", "IBG_VER": "V12R02",
        "IBG_SN": "10060006A02F24170091", "FHP_SN": ["10050013A00X23430165"],
        "BMS_SN": "10060006A02F24170091B1",
    })
    c = TestClient(app_module.create_app())
    d = c.get("/api/support-info").json()
    g = d["gateways"][0]
    assert g["model"] == "aGate X-01-AU" and g["country"] == "AU"
    assert g["hardware_model_id"] == 102 and g["apower_count"] == 1
    import json
    blob = json.dumps(d)
    for pii in ("10060006A02F24170091", "10050013A00X23430165", "192.168.0.110", "IBG_SN"):
        assert pii not in blob, f"PII leaked: {pii}"


def test_support_info_meta_and_no_creds(monkeypatch):
    c = TestClient(app_module.create_app())
    d = c.get("/api/support-info").json()
    assert set(("meta", "gateways", "system_setup", "integration", "billing")) <= set(d)
    assert d["meta"]["software_version"] and d["meta"]["platform"]
    # integration reports booleans/counts, never creds
    assert "cloud_configured" in d["integration"] and isinstance(d["integration"]["cloud_configured"], bool)
