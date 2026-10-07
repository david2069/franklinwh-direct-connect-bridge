"""Gateway hardware registry (SyHdVersion) and its effect on circuit detection.

SyHdVersion is FWHAI's sysHdVersionInt and arrives free in every 1101 login
manifest, so the region question that circuit detection previously answered by
inference has an authoritative source.
"""
from franklinwh_direct_connect_bridge import circuits, devicedb
from tests.test_circuits import AU_CFG, AU_METER

AU_MANIFEST = {"SyHdVersion": 102, "IBG_SN": "10060006A02F24170091",
               "IBG_VER": "V12R02B30D06_260304", "protocolVer": "V1.11.03"}


def test_au_gateway_identified():
    d = devicedb.describe(AU_MANIFEST)
    assert d["known"] and d["model"] == "aGate X-01-AU"
    assert d["sku"] == "AGT-R1V1-AU" and d["country"] == "AU"
    assert d["expected_circuits"] == 2


def test_unknown_model_is_not_guessed():
    d = devicedb.describe({"SyHdVersion": 999})
    assert d["known"] is False and d["model"] is None
    assert d["sy_hd_version"] == 999          # raw value still reported


def test_missing_manifest_field_is_safe():
    assert devicedb.describe({})["known"] is False
    assert devicedb.describe(None)["known"] is False


def test_compatible_accessories_are_model_scoped():
    sc = [a["sku"] for a in devicedb.compatible(102, "smart_circuits")]
    assert sc == ["ACCY-SCV2-US", "ACCY-SCV1-AU"]
    assert [a["sku"] for a in devicedb.compatible(102, "generator")] == ["ACCY-GENV1-AU"]
    # US-only SC must not be offered for an AU gateway
    assert "ACCY-SCV1-US" not in sc


def test_flag_detected_accessories_have_no_api_type():
    """FranklinWH returns accessoryType only for generator/smart circuits."""
    ahub = devicedb.ACCESSORIES[253]
    assert ahub["api_type"] is None and ahub["gateways"] == "all"
    assert devicedb.ACCESSORIES[301]["api_type"] == 3
    assert devicedb.ACCESSORIES[302]["api_type"] == 4


def test_model_rules_out_a_circuit_the_hardware_cannot_have():
    """Detection already rejects circuit 3 here, so the verdict is unchanged —
    but `source` records that the model agreed."""
    third = circuits.build(AU_CFG, AU_METER, expected=2)["circuits"][2]
    assert third["present"] is False and third["source"] == "model"


def test_model_overrides_positive_evidence_and_says_so():
    """A stale Sw3 block with real-looking data must not out-vote the hardware."""
    stale = {**AU_CFG, "Sw3Mode": 1,
             "Sw3Time": ["2026-01-02 06:00", "2026-01-02 07:00",
                         "2000-01-01 00:00", "2000-01-01 00:00"],
             "Sw3TimeEn": [1, 1, 0, 0]}
    without = circuits.build(stale, AU_METER)["circuits"][2]
    assert without["present"] is True          # evidence alone would say yes

    third = circuits.build(stale, AU_METER, expected=2)["circuits"][2]
    assert third["present"] is False
    assert any("gateway model has 2 circuits" in e for e in third["evidence_against"])


def test_model_cannot_manufacture_an_absent_circuit():
    """A 3-circuit model with no enclosure fitted must still read as absent."""
    bare = {f"Sw{i}{k}": v for i in (1, 2, 3)
            for k, v in (("Name", f"Circuits {i}"), ("Mode", 0), ("SocLowSet", 20),
                         ("TimeEn", [0] * 4), ("TimeSet", [0] * 4),
                         ("Time", ["2000-01-01 00:00"] * 4))}
    v = circuits.build(bare, {}, expected=3)
    assert v["count"] == 0 and v["installed"] is False


def test_explicit_setting_still_beats_the_model():
    v = circuits.build(AU_CFG, AU_METER, override="3", expected=2)
    assert v["count"] == 3 and v["source"] == "setting"


def test_source_reports_how_it_was_decided():
    assert circuits.build(AU_CFG, AU_METER, expected=2)["source"] == "model+detected"
    assert circuits.build(AU_CFG, AU_METER)["source"] == "detected"


# ── vendor Backwards Compatibility Statement (US V1.0, 21 Jul 2026) ──────────
def test_vendor_model_names_differ_from_fwhai_labels():
    """FWHAI says "aGate X-10"; the vendor document says "aGate X 1.1"."""
    assert devicedb.GATEWAYS[100]["vendor_model"] == "aGate X 1.1"
    assert devicedb.GATEWAYS[101]["vendor_model"] == "aGate X 1.3"


def test_au_gateway_has_no_vendor_model_because_the_doc_is_us_only():
    """The statement is revision "US V1.0" and lists no AU hardware."""
    assert devicedb.GATEWAYS[102]["vendor_model"] is None
    assert devicedb.describe(AU_MANIFEST)["vendor_model"] is None


def test_accessory_generation_split_matches_the_vendor_doc():
    assert devicedb.ACCESSORIES[201]["vendor_fit"] == "aGate X 1.0/1.1"
    assert devicedb.ACCESSORIES[203]["vendor_fit"] == "aGate X 1.3/1.3.1"
    assert devicedb.ACCESSORIES[202]["vendor_fit"] == "aGate X 1.0/1.1"
    assert devicedb.ACCESSORIES[204]["vendor_fit"] == "aGate X 1.3/1.3.1"


def test_sc_v2_au_discrepancy_is_recorded_not_hidden():
    """FWHAI lists SCV2-US for the AU gateway; the vendor doc scopes it to 1.3/1.3.1."""
    a = devicedb.ACCESSORIES[204]
    assert 102 in a["gateways"] and "vendor doc scopes SCV2" in a["note"]
