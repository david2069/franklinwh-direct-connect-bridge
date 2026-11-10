"""FEAT-HA-DASHBOARD-YAML — the copy-paste Home Assistant card.

The rule the whole thing exists to honour: **never emit a guessed entity id.** Home Assistant
appends `_2` when an object_id collides, so an id composed from what we published can be
wrong, and a card full of wrong ids shows dashes that look like broken hardware.
"""
from franklinwh_direct_connect_bridge import ha_dashboard as hd


def _rows():
    return [
        {"domain": "sensor", "object_id": "franklinwh_n_soc", "name": "SoC", "group": "core"},
        {"domain": "sensor", "object_id": "franklinwh_n_grid_w", "name": "Grid", "group": "power"},
        {"domain": "sensor", "object_id": "franklinwh_n_lat", "name": "Latency",
         "group": "diagnostic"},
        {"domain": "select", "object_id": "franklinwh_n_operating_mode", "name": "Mode",
         "group": "controls"},
    ]


# --- id resolution ------------------------------------------------------------------------

def test_exact_ids_are_used():
    found, missing = hd.resolve_ids(_rows(), {
        "sensor.franklinwh_n_soc", "sensor.franklinwh_n_grid_w",
        "sensor.franklinwh_n_lat", "select.franklinwh_n_operating_mode"})
    assert missing == []
    assert [f["entity_id"] for f in found][:1] == ["sensor.franklinwh_n_soc"]


def test_ha_collision_suffix_is_followed():
    """HA appends _2 on collision. The real id is the one to emit, not the one we expected."""
    found, _ = hd.resolve_ids(
        [_rows()[0]], {"sensor.franklinwh_n_soc_2"})
    assert found[0]["entity_id"] == "sensor.franklinwh_n_soc_2"


def test_entity_absent_from_ha_is_reported_not_guessed():
    found, missing = hd.resolve_ids([_rows()[0]], {"sensor.something_else"})
    assert found == []
    assert [m["object_id"] for m in missing] == ["franklinwh_n_soc"]


def test_a_near_miss_is_a_miss():
    """`..._soc_backup` is a different entity, not our _2. Only a numeric suffix counts."""
    found, missing = hd.resolve_ids([_rows()[0]], {"sensor.franklinwh_n_soc_backup"})
    assert found == [] and len(missing) == 1


def test_wrong_domain_does_not_match():
    found, missing = hd.resolve_ids([_rows()[3]], {"sensor.franklinwh_n_operating_mode"})
    assert found == [] and len(missing) == 1


# --- YAML ---------------------------------------------------------------------------------

def _yaml(**kw):
    found, _ = hd.resolve_ids(_rows(), {
        "sensor.franklinwh_n_soc", "sensor.franklinwh_n_grid_w",
        "sensor.franklinwh_n_lat", "select.franklinwh_n_operating_mode"})
    return hd.build_yaml(found, **kw)


def test_diagnostics_are_opt_in():
    assert "franklinwh_n_lat" not in _yaml()
    assert "franklinwh_n_lat" in _yaml(diagnostics=True)


def test_grouped_is_core_cards_only():
    y = _yaml()
    assert y.startswith("type: vertical-stack")
    assert "- type: entities" in y
    assert "show_header_toggle: false" in y and "state_color: true" in y
    # the agreed shape forbids these
    assert "custom:" not in y, "a custom card requires HACS; the agreed shape is core only"
    assert "theme:" not in y, "a theme line overrides the user's own dashboard theme"


def test_single_layout_is_one_card():
    y = _yaml(layout="single")
    assert y.startswith("type: entities") and y.count("type: entities") == 1


def test_empty_groups_are_omitted_not_blank():
    """An `entities:` key with nothing under it is invalid YAML to HA's card editor."""
    found, _ = hd.resolve_ids([_rows()[0]], {"sensor.franklinwh_n_soc"})
    y = hd.build_yaml(found)
    assert y.count("- type: entities") == 1
    assert "Power" not in y and "Controls" not in y


def test_nothing_found_yields_no_yaml():
    assert hd.build_yaml([]) == ""


# --- what we publish ----------------------------------------------------------------------

def test_rows_cover_sensors_and_controls_with_real_domains():
    rows = hd.rows_for_node("node1")
    assert rows, "no entities would ever be offered"
    assert all(r["object_id"].startswith("franklinwh_node1_") for r in rows)
    assert {"sensor", "select"} <= {r["domain"] for r in rows}
    assert "controls" in {r["group"] for r in rows}
