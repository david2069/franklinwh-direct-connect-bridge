"""#689: the Dashboard card found none of the bridge's entities on the owner's HA.

HA named them after the device and the entity name (``sensor.franklinwh_direct_<tail>_
state_of_charge``), not after the discovery ``object_id`` the card composed
(``sensor.franklinwh_<node>_soc``), so 0 of 47 matched and the message blamed the setup.
The card now asks HA for the ids of the bridge's own device and matches by entity name.
Ids below are as HA gave them on the HAOS test VM (2026-11-17).
"""
import io
import json

import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import (app as app_module, config, db, environment,
                                              ha_dashboard as hd, ha_instances, state)
from franklinwh_direct_connect_bridge.db import MetricsStore

TAIL = "b7cf5da2"
DEVICE = [f"sensor.franklinwh_direct_{TAIL}_state_of_charge",
          f"sensor.franklinwh_direct_{TAIL}_grid_power",
          f"sensor.franklinwh_direct_{TAIL}_round_trip_latency",
          f"select.franklinwh_direct_{TAIL}_operating_mode",
          f"sensor.franklinwh_direct_{TAIL}_operating_mode",
          f"binary_sensor.franklinwh_direct_{TAIL}_bridge_problem"]


def _rows():
    return [
        {"domain": "sensor", "object_id": "franklinwh_n_soc", "name": "State of Charge",
         "group": "core"},
        {"domain": "sensor", "object_id": "franklinwh_n_grid_w", "name": "Grid Power",
         "group": "power"},
        {"domain": "sensor", "object_id": "franklinwh_n_latency_ms",
         "name": "Round-trip Latency", "group": "diagnostic"},
        {"domain": "select", "object_id": "franklinwh_n_operating_mode",
         "name": "Operating Mode", "group": "controls"},
        {"domain": "sensor", "object_id": "franklinwh_n_mode", "name": "Operating Mode",
         "group": "core"},
    ]


def test_ids_ha_named_after_the_device_are_found():
    found, missing = hd.resolve_ids(_rows(), set(DEVICE), device_ids=set(DEVICE))
    assert missing == []
    assert [f["entity_id"] for f in found] == [
        f"sensor.franklinwh_direct_{TAIL}_state_of_charge",
        f"sensor.franklinwh_direct_{TAIL}_grid_power",
        f"sensor.franklinwh_direct_{TAIL}_round_trip_latency",
        f"select.franklinwh_direct_{TAIL}_operating_mode",
        f"sensor.franklinwh_direct_{TAIL}_operating_mode"]


def test_only_ids_ha_reports_a_state_for_are_used():
    """A disabled entity is on the device but has no state: it is missing, not guessed."""
    states = set(DEVICE) - {f"sensor.franklinwh_direct_{TAIL}_grid_power"}
    found, missing = hd.resolve_ids(_rows(), states, device_ids=set(DEVICE))
    assert [m["name"] for m in missing] == ["Grid Power"]


def test_another_device_with_the_same_names_is_not_used():
    other = {e.replace(TAIL, "other123") for e in DEVICE}
    found, missing = hd.resolve_ids(_rows(), set(DEVICE) | other, device_ids=set(DEVICE))
    assert all(TAIL in f["entity_id"] for f in found) and missing == []


def test_object_id_ids_still_work_without_the_device_list():
    found, missing = hd.resolve_ids(_rows()[:1], {"sensor.franklinwh_n_soc"})
    assert found[0]["entity_id"] == "sensor.franklinwh_n_soc" and missing == []


def test_binary_sensors_are_looked_up_as_binary_sensors():
    """The four binary sensors were offered as ``sensor.``, so they could never match."""
    from franklinwh_direct_connect_bridge.publish import entities as ents
    bins = {f"franklinwh_n_{e['key']}" for e in ents.ENTITIES
            if e.get("ha_type") == "binary_sensor"}
    assert bins
    rows = {r["object_id"]: r["domain"] for r in hd.rows_for_node("n")}
    assert all(rows[b] == "binary_sensor" for b in bins)


def test_device_entity_ids_asks_ha_for_the_bridge_device(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout=0):
        seen["template"] = json.loads(req.data)["template"]

        class R(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *a): return False
        return R(json.dumps(DEVICE).encode())
    monkeypatch.setattr(ha_instances.urllib.request, "urlopen", fake_urlopen)
    got = ha_instances.device_entity_ids("http://supervisor/core", "t", "franklinwh_n")
    assert got == DEVICE
    assert "'franklinwh_n'" in seen["template"] and "device_entities(d)" in seen["template"]
    with pytest.raises(ValueError):
        ha_instances.device_entity_ids("http://x", "t", "bad'id")


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    st = MetricsStore(str(tmp_path / "m.db"))
    monkeypatch.setattr(environment, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "_settings", None)
    monkeypatch.setattr(db, "get_store", lambda s: st)
    state.reset_gateways()
    st.create_ha_instance(ha_id="self", name="HA", base_url="http://supervisor/core",
                          token="t", is_default=True)
    gw = state.register_gateway("g1", "192.0.2.110", "aGate")
    gw.serial = "10060006A0000000B7CF5DA2"
    yield gw
    state.reset_gateways()


def test_the_card_uses_the_ids_ha_gave(ctx, monkeypatch):
    node = (getattr(ctx, "node", None) or ctx.serial.lower())
    full = DEVICE
    monkeypatch.setattr(ha_instances, "states", lambda u, t: [{"entity_id": e} for e in full])
    asked = {}
    monkeypatch.setattr(ha_instances, "device_entity_ids",
                        lambda u, t, ident: asked.setdefault("ident", ident) and full)
    d = TestClient(app_module.create_app()).get("/api/ha/dashboard-yaml?gateway=g1").json()
    assert asked["ident"] == f"fwh_dc_{node}"
    assert f"sensor.franklinwh_direct_{TAIL}_state_of_charge" in d["yaml"]
    assert d["found"] >= 4 and d["hint"] == ""


def test_nothing_found_says_so_in_plain_words(ctx, monkeypatch):
    monkeypatch.setattr(ha_instances, "states", lambda u, t: [{"entity_id": "sensor.other"}])
    monkeypatch.setattr(ha_instances, "device_entity_ids", lambda u, t, ident: [])
    d = TestClient(app_module.create_app()).get("/api/ha/dashboard-yaml?gateway=g1").json()
    assert d["yaml"] == ""
    assert d["hint"].startswith("Home Assistant has no entities from this gateway yet")
    assert "discovery prefix" not in d["hint"]


def test_the_card_says_what_it_is_and_numbers_the_steps():
    import pathlib
    html = (pathlib.Path(app_module.__file__).parent / "templates" / "tabs" / "ha.html").read_text()
    card = html[html.index("Dashboard card"):html.index("published but not found") + 200]
    assert "ready-made Home Assistant card" in card
    assert 'data-testid="dash-steps"' in card and card.count("<li>") == 4
    assert "m.name" in card and "m.expected" not in card     # left-out entities by name
