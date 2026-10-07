"""Field-schema port + /api/schema + /api/catalog labelling metadata."""

from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import app as app_module
from franklinwh_direct_connect_bridge import fieldschema as fs


def _app():
    return TestClient(app_module.create_app())


def test_describe_field_known_key():
    d = fs.describe_field("p_fhp")
    assert d == {"label": "Battery use", "group": "Power Flow", "unit": "kW"}


def test_describe_field_strips_array_index():
    # pro_load_pwr[0] must collapse onto the base key pro_load_pwr.
    base = fs.describe_field("pro_load_pwr")
    idx = fs.describe_field("pro_load_pwr[0]")
    assert idx is not None and idx == base
    assert idx["group"] == "Power Flow"


def test_describe_field_unknown_returns_none():
    assert fs.describe_field("totally_not_a_field") is None
    assert fs.describe_field(None) is None


def test_field_schema_map_populated():
    assert isinstance(fs.FIELD_SCHEMA, dict) and len(fs.FIELD_SCHEMA) > 50
    # No 'derived' pseudo-key leaks into the reverse index.
    assert "derived" not in fs.FIELD_SCHEMA


def test_api_schema_endpoint():
    r = _app().get("/api/schema")
    assert r.status_code == 200
    d = r.json()
    assert d and "p_fhp" in d and "t_amb" in d and "kwh_fhp_chg" in d
    assert d["t_amb"]["group"] == "Environment"
    assert d["kwh_fhp_chg"]["unit"] == "kWh"


def test_describe_indexed_specific_and_generic():
    # main_sw[0] is a DEFINED per-index key → the specific grid_relay1 label.
    d0 = fs.describe_indexed("main_sw", 0)
    assert "Grid" in d0["label"] and d0["group"] == "Relays"
    # generator_relay / solar_relay1 for [1]/[2].
    assert "Generator" in fs.describe_indexed("main_sw", 1)["label"]
    assert "Solar" in fs.describe_indexed("main_sw", 2)["label"]
    # fhpSoc has no per-index schema entry → generic "<base label> [i]" from the base.
    dg = fs.describe_indexed("fhpSoc", 0)
    assert dg["label"].endswith("[0]") and dg["group"] == "Battery Packs"


def test_indexed_keys_present_in_reverse_index():
    # Per-index keys are retained alongside the collapsed base key.
    assert "main_sw[0]" in fs.FIELD_SCHEMA and "main_sw" in fs.FIELD_SCHEMA
    assert fs.FIELD_SCHEMA["pro_load[0]"]["group"] == "Smart Circuits"


def test_local_supplement_resolves():
    # TOU tariff-tier buckets are grouped + labelled (not "Other").
    peak = fs.describe_field("peak")
    assert peak["group"] == "TOU" and "Peak" in peak["label"]
    for k in ("sharp", "flat", "valley"):
        assert fs.describe_field(k)["group"] == "TOU"
    # solar_pv / relay_status locals.
    assert fs.describe_field("installPV2port")["group"] == "Solar PV"
    assert fs.describe_field("gridRelayAdhesion")["group"] == "Relays"


def test_run_status_enum():
    rs = fs.describe_field("run_status")
    assert rs is not None and rs["enum"][1] == "Charging"
    assert fs.ENUMS["run_status"][2] == "Discharging"


def test_api_schema_includes_indexed_enum_and_locals():
    d = _app().get("/api/schema").json()
    # Indexed key + local supplement keys are exposed to the UI.
    assert d.get("main_sw[0]") and d["main_sw[0]"]["group"] == "Relays"
    assert d.get("installPV1port") and d.get("installPV2port")
    assert d.get("peak", {}).get("group") == "TOU"
    # Enum survives JSON round-trip (int key -> str key "1").
    enum = (d.get("run_status") or {}).get("enum")
    assert enum and enum.get("1") == "Charging"


def test_api_catalog_endpoint():
    r = _app().get("/api/catalog")
    assert r.status_code == 200
    d = r.json()
    assert "power_flow" in d
    pf = d["power_flow"]
    assert pf["description"] and pf["write"] is False
    # A write-recipe cmdType (e.g. offgrid, cmd 1723) is flagged writable.
    assert d.get("offgrid", {}).get("write") is True
