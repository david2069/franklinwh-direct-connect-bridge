"""aGate models come from franklinwh-cloud's device catalogue (0.6.5 ships it)."""

import sys
import types

import pytest

from franklinwh_direct_connect_bridge import devicedb


def _fake_catalog(monkeypatch, agate_models):
    mod = types.ModuleType("franklinwh_cloud.discovery")
    mod.get_catalog = lambda: {
        "countries": {"2": {"code": "US"}, "3": {"code": "AU"}},
        "agate_models": agate_models,
    }
    monkeypatch.setitem(sys.modules, "franklinwh_cloud.discovery", mod)


def test_a_model_only_the_catalogue_knows_is_named(monkeypatch):
    _fake_catalog(monkeypatch, {"105": {"model": "aGate X 30", "sku": "AGT-R1V4-US",
                                        "country_id": 2}})
    g = devicedb.gateway(105)
    assert g["model"] == "aGate X 30"
    assert g["sku"] == "AGT-R1V4-US"
    assert g["country"] == "US"
    assert g["amps"] is None and g["circuits"] is None    # not in the catalogue


def test_the_catalogue_name_wins_and_bridge_fields_stay(monkeypatch):
    _fake_catalog(monkeypatch, {"102": {"model": "aGate X-01-AU (cat)",
                                        "sku": "AGT-R1V1-AU", "country_id": 3}})
    g = devicedb.gateway("102")
    assert g["model"] == "aGate X-01-AU (cat)"
    assert g["amps"] == 100 and g["circuits"] == 2


def test_without_the_cloud_library_the_local_table_answers(monkeypatch):
    monkeypatch.setitem(sys.modules, "franklinwh_cloud.discovery", None)
    assert devicedb.gateway(102) == devicedb.GATEWAYS[102]
    assert devicedb.gateway(105) is None
    assert devicedb.gateway("x") is None


def test_the_pinned_catalogue_agrees_with_the_local_table():
    """Drift check against the real franklinwh-cloud 0.6.5 catalogue."""
    discovery = pytest.importorskip("franklinwh_cloud.discovery")
    cat = discovery.get_catalog()
    for gid, row in devicedb.GATEWAYS.items():
        c = cat["agate_models"][str(gid)]
        assert (c["model"], c["sku"]) == (row["model"], row["sku"]), gid
        assert cat["countries"][str(c["country_id"])]["code"] == row["country"], gid
