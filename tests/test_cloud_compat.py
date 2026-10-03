"""Fidelity tests for the cloud-aligned facade (cloud_compat + /api/cloud/*).

The key-parity tests import ``franklinwh_cloud`` (TEST-ONLY dependency) and assert
that the bridge's hand-replicated dicts have EXACTLY the same keys as the real
cloud dataclasses — so any drift in the cloud models is caught here. They skip
cleanly (importorskip) when the cloud lib is not installed; the plain endpoint
shape tests below run regardless.
"""

from fastapi.testclient import TestClient

from franklinwh_local_bridge import app as app_module
from franklinwh_local_bridge import client as client_module
from franklinwh_local_bridge import cloud_compat


# A representative local power_flow (1301) payload, cloud-style raw keys.
SAMPLE_PF = {
    "opt": 0, "result": 0, "mode": 29287, "name": "Time-of-Use",
    "run_status": 1, "p_uti": -120.7, "p_sun": 1669.1, "p_gen": 0.0,
    "p_fhp": -362.0, "p_load": 1186.4, "soc": 69.2, "t_amb": 20.5,
}

# A smart_circuits (1409) payload with one named/on circuit (as the emulator emits).
SAMPLE_SW = {"opt": 0, "result": 0, "SwMerge": 0, "Sw1Name": "Circuit 1", "Sw1Mode": 1}

# A representative local mode_list (1726): 3 modes, Time-of-Use active. scheduling_type
# is the cloud workMode (TOU=1, Self=2, Backup=3).
SAMPLE_MODE_LIST = {
    "opt": 0, "result": 0, "current_id": 29287,
    "list": [
        {"id": 85232, "name": "Self-Consumption", "reserved_soc": 20,
         "scheduling_type": 2, "electricity_type": 0},
        {"id": 29287, "name": "Time-of-Use", "reserved_soc": 30,
         "scheduling_type": 1, "electricity_type": 0},
        {"id": 11001, "name": "Emergency Backup", "reserved_soc": 100,
         "scheduling_type": 3, "electricity_type": 0},
    ],
}

# A representative local mode_soc (1406): per-mode min/max reserve SoC.
SAMPLE_MODE_SOC = {
    "opt": 0, "result": 0,
    "selfMinSoc": 10, "selfMaxSoc": 90, "touMinSoc": 15, "touMaxSoc": 95,
}

# The exact key set cloud get_all_mode_soc() emits per entry.
RESERVE_KEYS = {"workMode", "name", "soc", "minSoc", "maxSoc", "editSocFlag", "active"}

# A local ibg_run_status (1708) payload.
SAMPLE_IBG_RUN = {"opt": 0, "result": 0, "ibgRunStatus": 29287,
                  "name": "Time-of-Use", "energyMode": 1}

# A local relay_status (1710) payload — primary contactor adhesion/open flags.
SAMPLE_RELAY = {"opt": 0, "result": 0, "gridRelayAdhesion": 0, "gridRelayOpen": 1,
                "genRelayAdhesion": 0, "genRelayOpen": 0}

# A local device_info (1116) payload.
SAMPLE_DEVICE_INFO = {"opt": 0, "result": 0, "usrName": "Home",
                      "distributor": "ACME Solar", "installerId": "INST-42"}

# A local network_interfaces (1118) commSetPara block (firmware field names).
SAMPLE_COMM = {
    "currentNetType": 3,
    "wifiMAC": "AA:BB:CC:DD:EE:FF", "wifiDHCP": 1, "wifiStaticIP": "192.0.2.110",
    "wifiDNS": "8.8.8.8", "wifiGateWay": "192.0.2.1",
    "eth0MAC": "88:C9:B3:20:00:80", "eth0DHCP": 0, "eth0StaticIP": "0.0.0.0",
    "eth0DNS": "8.8.8.8", "eth0GateWay": "172.16.1.1",
    "eth1MAC": "88:C9:B3:21:2C:B8", "eth1DHCP": 1, "eth1StaticIP": "0.0.0.0",
    "eth1DNS": "8.8.8.8", "eth1GateWay": "0.0.0.0",
    "operatorMAC": "0E:4B:51:E6:81:08", "operatorDNS": "192.192.192.192", "operatorRSSI": 21,
    "awsStatus": 1,
}
SAMPLE_NETWORK = {"opt": 0, "result": 0, "commSetPara": SAMPLE_COMM}

# Raw cmdType-211 keys cloud get_power_info() surfaces (see stats.py get_stats()).
POWER_INFO_KEYS = {
    "gridLineVol", "gridVol1", "gridVol2", "gridCurr1", "gridCurr2", "gridFreq",
    "dspSetFreq", "genVoltage", "loadCurr1", "loadCurr2",
    "gridRelay2", "blackStartRelay", "pvRelay2", "BFPVApboxRelay",
    "loadRelay1Stat", "loadRelay2Stat", "evRelayStat",
    "loadSolarRelay1Stat", "loadSolarRelay2Stat",
    "dspRunStatus", "ibgRunStatus", "electricity_type",
}


def _app():
    return TestClient(app_module.create_app())


# ── Plain (no cloud dep) shape tests ─────────────────────────────────────────

def test_stats_top_level_shape():
    out = cloud_compat.stats_from_power_flow(SAMPLE_PF)
    assert set(out.keys()) == {"current", "totals", "is_stale"}
    assert out["is_stale"] is False


def test_stats_core_fields_mapped():
    out = cloud_compat.stats_from_power_flow(SAMPLE_PF, sw_payload=SAMPLE_SW)
    cur = out["current"]
    assert cur["solar_production"] == 1669.1
    assert cur["generator_production"] == 0.0
    assert cur["battery_use"] == -362.0
    assert cur["grid_use"] == -120.7
    assert cur["home_load"] == 1186.4
    assert cur["battery_soc"] == 69.2
    assert cur["agate_ambient_temparture"] == 20.5
    assert cur["run_status"] == 1
    assert cur["run_status_desc"] == "Charging"
    assert cur["work_mode"] == 1               # Time-of-Use → cloud workMode 1
    assert cur["work_mode_desc"] == "Time-of-Use"
    assert cur["effective_mode"] == "Time-of-Use"
    assert cur["grid_connection_state"] == "Connected"
    assert cur["switch_1_state"] == 1          # from Sw1Mode


def test_stats_vpp_effective_mode():
    pf = dict(SAMPLE_PF, run_status=9)
    out = cloud_compat.stats_from_power_flow(pf)
    assert out["current"]["effective_mode"] == "VPP mode"


def test_stats_totals_default_when_no_kwh():
    out = cloud_compat.stats_from_power_flow(SAMPLE_PF)
    assert all(v == 0.0 for v in out["totals"].values())


def test_stats_totals_mapped_when_kwh_present():
    pf = dict(SAMPLE_PF, kwh_fhp_chg=5.5, kwh_uti_in=3.2, kwh_sun=9.9)
    out = cloud_compat.stats_from_power_flow(pf)
    assert out["totals"]["battery_charge"] == 5.5
    assert out["totals"]["grid_import"] == 3.2
    assert out["totals"]["solar"] == 9.9


def test_smart_circuit_detail_named_and_default():
    d1 = cloud_compat.smart_circuit_detail(SAMPLE_SW, 1)
    assert d1["id"] == 1 and d1["name"] == "Circuit 1" and d1["is_on"] is True
    d2 = cloud_compat.smart_circuit_detail(SAMPLE_SW, 2)
    assert d2["name"] == "" and d2["mode"] == 0 and d2["is_on"] is False
    assert d2["open_time"] is None and d2["time_enabled"] is None


def test_smart_circuits_map_string_keys():
    m = cloud_compat.smart_circuits_map(SAMPLE_SW)
    assert set(m.keys()) == {"1", "2", "3"}
    assert m["1"]["name"] == "Circuit 1"


# ── Phase 2 translation fns (pure, no I/O) ───────────────────────────────────

def test_reserves_is_list_with_exact_keys():
    out = cloud_compat.reserves_from_mode_list(SAMPLE_MODE_LIST, SAMPLE_MODE_SOC)
    assert isinstance(out, list) and len(out) == 3
    for entry in out:
        assert set(entry.keys()) == RESERVE_KEYS


def test_reserves_active_flag_and_mapping():
    out = cloud_compat.reserves_from_mode_list(SAMPLE_MODE_LIST, SAMPLE_MODE_SOC)
    by_wm = {e["workMode"]: e for e in out}
    # Time-of-Use (workMode 1) is the current_id → active.
    assert by_wm[1]["active"] is True
    assert by_wm[2]["active"] is False and by_wm[3]["active"] is False
    # name ← name, soc ← reserved_soc, min/max ← mode_soc per workMode.
    assert by_wm[1]["name"] == "Time-of-Use" and by_wm[1]["soc"] == 30
    assert by_wm[1]["minSoc"] == 15 and by_wm[1]["maxSoc"] == 95      # touMin/Max
    assert by_wm[2]["minSoc"] == 10 and by_wm[2]["maxSoc"] == 90      # selfMin/Max
    # Emergency Backup (3) has no min/max in mode_soc → cloud defaults 0/100.
    assert by_wm[3]["minSoc"] == 0 and by_wm[3]["maxSoc"] == 100
    # editSocFlag is always the default (local can't supply it).
    assert all(e["editSocFlag"] == 0 for e in out)


def test_reserves_defaults_when_no_mode_soc():
    out = cloud_compat.reserves_from_mode_list(SAMPLE_MODE_LIST)
    assert all(e["minSoc"] == 0 and e["maxSoc"] == 100 for e in out)


SAMPLE_TOU_SCHEDULE = {"opt": 0, "result": 0, "touStrategy": 1,
                       "workdayLv": 2, "weekendLv": 1}


def test_tou_full_envelope_and_result_list():
    out = cloud_compat.tou_from_mode_list(SAMPLE_MODE_LIST, SAMPLE_TOU_SCHEDULE)
    # Full cloud return envelope, not just result.
    assert out["code"] == 200 and out["message"] == "SUCCESS"
    result = out["result"]
    # currendId ← current_id; result.list mirrors the operating-mode list.
    assert result["currendId"] == 29287
    assert isinstance(result["list"], list) and len(result["list"]) == 3
    for item in result["list"]:
        assert {"id", "name", "workMode", "soc"} <= set(item.keys())
    # current_id must correspond to exactly one list item (active/current_id consistent).
    active = [it for it in result["list"] if it["id"] == result["currendId"]]
    assert len(active) == 1 and active[0]["name"] == "Time-of-Use"
    # Per-item mapping: workMode ← scheduling_type, soc ← reserved_soc.
    by_id = {it["id"]: it for it in result["list"]}
    assert by_id[29287]["workMode"] == 1 and by_id[29287]["soc"] == 30
    assert by_id[85232]["workMode"] == 2 and by_id[11001]["workMode"] == 3
    # Cloud-only per-item keys defaulted.
    assert all(it["editSocFlag"] == 0 and it["oldIndex"] == 0
               and it["minSoc"] == 0 and it["maxSoc"] == 100 for it in result["list"])
    # Enriched with local tou_schedule strategy/flags; envelope keys dropped.
    assert result["touStrategy"] == 1 and result["workdayLv"] == 2
    assert "opt" not in result
    # Documented cloud result-level keys defaulted.
    for k in ("timers", "stopMode", "stromEn", "gridChargeEn", "touSendStatus"):
        assert k in result


def test_tou_works_without_schedule():
    out = cloud_compat.tou_from_mode_list(SAMPLE_MODE_LIST)
    result = out["result"]
    assert result["currendId"] == 29287 and len(result["list"]) == 3
    assert "touStrategy" not in result          # no enrichment source


def test_runtime_documented_keys_and_mapping():
    out = cloud_compat.runtime_from_ibg_run_status(SAMPLE_IBG_RUN)
    expected = {"ibgRunStatus", "name", "energyMode",
                "gridRelay2", "pvRelay2", "BlackStartRelay",
                "sinLTemp", "sinHTemp", "t_amb"}
    assert set(out.keys()) == expected
    assert out["ibgRunStatus"] == 29287 and out["name"] == "Time-of-Use"
    assert out["energyMode"] == 1
    # cloud-carried extras the local read can't supply → defaulted.
    assert out["gridRelay2"] == 0 and out["t_amb"] == 0


def test_power_info_contains_211_keys_and_passes_relays():
    out = cloud_compat.power_info_from_relay_status(SAMPLE_RELAY)
    # Every documented raw-211 field is present (defaulted).
    assert POWER_INFO_KEYS <= set(out.keys())
    assert out["gridFreq"] == 0 and out["gridVol1"] == 0
    # Local contactor flags pass through unchanged.
    assert out["gridRelayOpen"] == 1 and out["gridRelayAdhesion"] == 0
    assert out["genRelayAdhesion"] == 0 and out["genRelayOpen"] == 0


def test_device_info_passthrough():
    out = cloud_compat.device_info_passthrough(SAMPLE_DEVICE_INFO)
    assert out == SAMPLE_DEVICE_INFO
    assert out is not SAMPLE_DEVICE_INFO          # copy, not alias


def test_network_shape_and_mapping():
    out = cloud_compat.network_from_interfaces(SAMPLE_NETWORK)
    assert set(out.keys()) == {"currentNetType", "wifi", "eth0", "eth1",
                               "operator", "awsStatus"}
    assert set(out["wifi"].keys()) == {"mac", "dhcp", "ip", "dns", "gateway"}
    assert out["currentNetType"] == 3 and out["awsStatus"] == 1
    assert out["wifi"]["mac"] == "AA:BB:CC:DD:EE:FF"
    assert out["wifi"]["dhcp"] is True            # wifiDHCP 1 → True
    assert out["eth0"]["dhcp"] is False           # eth0DHCP 0 → False
    assert out["operator"]["rssi"] == 21


def test_network_accepts_flat_and_nested():
    # Flat top-level commSetPara block (no envelope) resolves the same.
    flat = cloud_compat.network_from_interfaces(SAMPLE_COMM)
    nested = cloud_compat.network_from_interfaces({"result": {"commSetPara": SAMPLE_COMM}})
    assert flat["wifi"]["mac"] == nested["wifi"]["mac"] == "AA:BB:CC:DD:EE:FF"


# ── Endpoint shape tests (monkeypatched client) ──────────────────────────────

def test_cloud_reserves_endpoint(monkeypatch):
    monkeypatch.setattr(client_module, "cloud_reserves",
                        lambda s, host=None: cloud_compat.reserves_from_mode_list(SAMPLE_MODE_LIST, SAMPLE_MODE_SOC))
    r = _app().get("/api/cloud/reserves")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list) and len(body) == 3
    assert set(body[0].keys()) == RESERVE_KEYS


def test_cloud_reserves_endpoint_502(monkeypatch):
    from franklinwh_local.transport import TransportError

    def boom(s, host=None):
        raise TransportError("host is down")

    monkeypatch.setattr(client_module, "cloud_reserves", boom)
    assert _app().get("/api/cloud/reserves").status_code == 502


def test_cloud_tou_endpoint(monkeypatch):
    monkeypatch.setattr(client_module, "cloud_tou",
                        lambda s, host=None: cloud_compat.tou_from_mode_list(SAMPLE_MODE_LIST, SAMPLE_TOU_SCHEDULE))
    r = _app().get("/api/cloud/tou")
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {"code", "message", "result"}
    assert body["result"]["currendId"] == 29287
    assert len(body["result"]["list"]) == 3


def test_cloud_tou_endpoint_502(monkeypatch):
    from franklinwh_local.transport import TransportError

    def boom(s, host=None):
        raise TransportError("host is down")

    monkeypatch.setattr(client_module, "cloud_tou", boom)
    assert _app().get("/api/cloud/tou").status_code == 502


def test_cloud_runtime_endpoint(monkeypatch):
    monkeypatch.setattr(client_module, "read", lambda s, name, host=None: SAMPLE_IBG_RUN)
    r = _app().get("/api/cloud/runtime")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, dict)
    assert body["ibgRunStatus"] == 29287 and "t_amb" in body


def test_cloud_power_info_endpoint(monkeypatch):
    monkeypatch.setattr(client_module, "read", lambda s, name, host=None: SAMPLE_RELAY)
    r = _app().get("/api/cloud/power-info")
    assert r.status_code == 200
    body = r.json()
    assert POWER_INFO_KEYS <= set(body.keys())
    assert body["gridRelayOpen"] == 1


def test_cloud_device_info_endpoint(monkeypatch):
    monkeypatch.setattr(client_module, "read", lambda s, name, host=None: SAMPLE_DEVICE_INFO)
    r = _app().get("/api/cloud/device-info")
    assert r.status_code == 200
    assert r.json() == SAMPLE_DEVICE_INFO


def test_cloud_network_endpoint(monkeypatch):
    monkeypatch.setattr(client_module, "read", lambda s, name, host=None: SAMPLE_NETWORK)
    r = _app().get("/api/cloud/network")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, dict)
    assert set(body.keys()) == {"currentNetType", "wifi", "eth0", "eth1",
                                "operator", "awsStatus"}


def test_cloud_facade_502_on_device_error(monkeypatch):
    from franklinwh_local.transport import TransportError

    def boom(s, name, host=None):
        raise TransportError("host is down")

    monkeypatch.setattr(client_module, "read", boom)
    # tou/reserves use their own two-read client helpers (covered by dedicated 502 tests).
    for route in ("runtime", "power-info", "device-info", "network"):
        assert _app().get(f"/api/cloud/{route}").status_code == 502


# ── Endpoint shape tests (monkeypatched client) [phase 1] ────────────────────

def test_cloud_stats_endpoint(monkeypatch):
    monkeypatch.setattr(client_module, "cloud_stats",
                        lambda s, host=None: cloud_compat.stats_from_power_flow(SAMPLE_PF, sw_payload=SAMPLE_SW))
    r = _app().get("/api/cloud/stats")
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {"current", "totals", "is_stale"}
    assert body["current"]["battery_soc"] == 69.2


def test_cloud_stats_endpoint_502(monkeypatch):
    from franklinwh_local.transport import TransportError

    def boom(s, host=None):
        raise TransportError("host is down")

    monkeypatch.setattr(client_module, "cloud_stats", boom)
    assert _app().get("/api/cloud/stats").status_code == 502


def test_cloud_smart_circuits_endpoint(monkeypatch):
    monkeypatch.setattr(client_module, "read", lambda s, name, host=None: SAMPLE_SW)
    r = _app().get("/api/cloud/smart-circuits")
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {"1", "2", "3"}
    assert body["1"]["name"] == "Circuit 1" and body["1"]["is_on"] is True


def test_cloud_smart_circuits_info_endpoint(monkeypatch):
    monkeypatch.setattr(client_module, "read", lambda s, name, host=None: SAMPLE_SW)
    r = _app().get("/api/cloud/smart-circuits/info")
    assert r.status_code == 200
    assert r.json() == SAMPLE_SW


def test_cloud_smart_circuits_502(monkeypatch):
    from franklinwh_local.transport import TransportError

    def boom(s, name, host=None):
        raise TransportError("host is down")

    monkeypatch.setattr(client_module, "read", boom)
    assert _app().get("/api/cloud/smart-circuits").status_code == 502


# ── Cloud-model key-parity tests (skip if franklinwh_cloud not installed) ─────

def test_current_key_parity():
    import dataclasses
    import pytest
    franklinwh_cloud = pytest.importorskip("franklinwh_cloud")
    from franklinwh_cloud.models import empty_stats

    current = cloud_compat.stats_from_power_flow(SAMPLE_PF)["current"]
    assert set(current.keys()) == set(dataclasses.asdict(empty_stats().current))


def test_totals_key_parity():
    import dataclasses
    import pytest
    pytest.importorskip("franklinwh_cloud")
    from franklinwh_cloud.models import empty_stats

    totals = cloud_compat.stats_from_power_flow(SAMPLE_PF)["totals"]
    assert set(totals.keys()) == set(dataclasses.asdict(empty_stats().totals))


def test_smart_circuit_detail_matches_cloud():
    import dataclasses
    import pytest
    pytest.importorskip("franklinwh_cloud")
    from franklinwh_cloud.models import SmartCircuitDetail

    for cid in (1, 2, 3):
        expected = dataclasses.asdict(SmartCircuitDetail.from_api_payload(SAMPLE_SW, cid))
        assert cloud_compat.smart_circuit_detail(SAMPLE_SW, cid) == expected


def test_reserves_workmodes_are_valid_operating_modes():
    """The workMode ints we emit are the real cloud OPERATING_MODES ids."""
    import pytest
    pytest.importorskip("franklinwh_cloud")
    from franklinwh_cloud.mixins.modes import OPERATING_MODES

    out = cloud_compat.reserves_from_mode_list(SAMPLE_MODE_LIST, SAMPLE_MODE_SOC)
    for entry in out:
        assert entry["workMode"] in OPERATING_MODES     # 1/2/3 are canonical mode ids


def test_network_matches_real_get_network_info():
    """Our translation reproduces the real cloud get_network_info() output for the
    same underlying commSetPara block (parity against the actual method)."""
    import asyncio
    import json
    from unittest.mock import AsyncMock, MagicMock

    import pytest
    pytest.importorskip("franklinwh_cloud")
    from franklinwh_cloud.mixins.devices import DevicesMixin

    client = MagicMock(spec=DevicesMixin)
    client.gateway = "TEST_GATEWAY"
    client._build_payload = MagicMock(return_value={"dummy": True})
    client._mqtt_send = AsyncMock(return_value={
        "result": {"dataArea": json.dumps({"result": {"commSetPara": SAMPLE_COMM}})}
    })
    client.get_network_info = DevicesMixin.get_network_info.__get__(client)
    expected = asyncio.run(client.get_network_info())

    assert cloud_compat.network_from_interfaces(SAMPLE_NETWORK) == expected


def test_mode_from_reads_active_requested_and_index_safety():
    """Cloud get_mode flat dict from local reads; also pins workMode->name (index safety:
    workMode 1 is TOU not Backup)."""
    from franklinwh_local_bridge import cloud_compat
    pf = {"run_status": 2, "soc": 44.3, "name": "Self-Consumption"}
    ml = {"current_id": 85232, "list": [
        {"id": 85232, "name": "Self-Consumption", "scheduling_type": 2, "reserved_soc": 5, "electricity_type": 1},
        {"id": 29287, "name": "Time-of-Use", "scheduling_type": 1, "reserved_soc": 15, "electricity_type": 1},
        {"id": 47522, "name": "Emergency Backup", "scheduling_type": 3, "reserved_soc": 100, "electricity_type": 1},
    ]}
    ms = {"selfMinSoc": 5, "selfMaxSoc": 100, "touMinSoc": 10, "touMaxSoc": 100}
    m = cloud_compat.mode_from_reads(pf, ml, ms)  # active = current_id 85232 (Self, wm 2)
    assert m["currendId"] == 85232 and m["workMode"] == 2 and m["name"] == "Self-Consumption"
    assert m["soc"] == 5 and m["minSoc"] == 5 and m["maxSoc"] == 100
    assert m["run_status"] == 2 and "run_desc" in m
    assert {"deviceStatus", "valid", "unreadMsgCount", "offgridState", "editSocFlag"} <= set(m)
    t = cloud_compat.mode_from_reads(pf, ml, ms, tou_schedule={"touStrategy": 1, "opt": 0}, requested_workmode=1)
    assert t["workMode"] == 1 and t["name"] == "Time-of-Use"          # wm1 -> TOU, not Backup
    assert "touAlertMessage" in t and t["touScheduleList"] == {"touStrategy": 1}
    b = cloud_compat.mode_from_reads(pf, ml, ms, requested_workmode=3)
    assert b["workMode"] == 3 and b["name"] == "Emergency Backup" and "backupForeverFlag" in b
    assert "error" in cloud_compat.mode_from_reads(pf, {"current_id": 1, "list": []})


# ── mode naming: canonical, never the tariff ─────────────────────────────────
# The local broker labels the TOU mode with the site's tariff name (observed:
# "Solar & Battery Plan"), which the cloud does NOT do — getGatewayTouListV2
# returns "Time-of-Use" for the same id. FWHAI overrides it for the same reason.
_ML_WITH_TARIFF = {
    "current_id": 85232,
    "list": [
        {"id": 47522, "name": "Emergency Backup", "reserved_soc": 100,
         "scheduling_type": 3, "electricity_type": 1},
        {"id": 85232, "name": "Self-Consumption", "reserved_soc": 11,
         "scheduling_type": 2, "electricity_type": 1},
        {"id": 29287, "name": "Solar & Battery Plan", "reserved_soc": 15,
         "scheduling_type": 1, "electricity_type": 1},
    ],
}


def test_reserves_report_canonical_mode_names_not_the_tariff():
    names = {r["workMode"]: r["name"]
             for r in cloud_compat.reserves_from_mode_list(_ML_WITH_TARIFF)}
    assert names == {1: "Time-of-Use", 2: "Self-Consumption", 3: "Emergency Backup"}
    assert "Solar & Battery Plan" not in names.values()


def test_tou_list_reports_canonical_mode_names():
    items = cloud_compat.tou_from_mode_list(_ML_WITH_TARIFF)["result"]["list"]
    assert {i["workMode"]: i["name"] for i in items}[1] == "Time-of-Use"


def test_mode_from_reads_canonicalises_and_keeps_the_tariff():
    """The tariff is useful — it just must not masquerade as the mode name."""
    out = cloud_compat.mode_from_reads(
        {"run_status": 0}, {**_ML_WITH_TARIFF, "current_id": 29287})
    assert out["name"] == "Time-of-Use" and out["modeName"] == "Time-of-Use"
    assert out["tariffName"] == "Solar & Battery Plan"


def test_tariff_name_is_none_when_it_adds_nothing():
    out = cloud_compat.mode_from_reads({"run_status": 0}, _ML_WITH_TARIFF)
    assert out["name"] == "Self-Consumption" and out["tariffName"] is None


def test_reserved_soc_survives_the_rename():
    """Canonicalising the label must not disturb the values."""
    socs = {r["workMode"]: r["soc"]
            for r in cloud_compat.reserves_from_mode_list(_ML_WITH_TARIFF)}
    assert socs == {1: 15, 2: 11, 3: 100}
