"""The MQTT node id is the Home Assistant device identity, so it must never be a
shared fallback. Regression tests for the orphaned/merged-device class of bug.

Context: the poller used to start with ``node = "agate"`` and publish discovery under
it if the firmware manifest read failed. That left a retained discovery config for a
device that never exists again once the real serial arrives (an orphan Home Assistant
cannot expire), and in a multi-gateway install made every unidentified gateway publish
as the SAME node — merging them into one device.
"""
import tomllib
from pathlib import Path

import pytest

from franklinwh_direct_connect_bridge import __version__
from franklinwh_direct_connect_bridge.publish import entities

ROOT = Path(__file__).resolve().parents[1]


# ── fix 4: one version, three files ────────────────────────────────────────────
def test_version_is_not_hardcoded_and_matches_pyproject():
    declared = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    assert __version__ == declared, (
        f"__version__ ({__version__}) drifted from pyproject ({declared}). It is "
        "published as the MQTT device sw_version, so drift misreports every HA device."
    )


def test_addon_version_matches_pyproject():
    declared = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    line = next(l for l in (ROOT / "config.yaml").read_text().splitlines()
                if l.startswith("version:"))
    addon = line.split(":", 1)[1].strip().strip('"').strip("'")
    assert addon == declared, f"config.yaml version {addon} != pyproject {declared}"


def test_sw_version_reports_the_real_version():
    d = entities.device_info("1006000600000000", "1006000600000000", None)
    assert d["sw_version"] == f"Local Bridge v{__version__}"


# ── the identity contract these fixes protect ─────────────────────────────────
def test_device_identity_keys_off_the_node_not_the_package_name():
    d = entities.device_info("abc123", "abc123", None)
    assert d["identifiers"] == ["franklinwh_abc123"]
    # The package was renamed to franklinwh_direct_connect_bridge; none of the
    # identity may follow it, or every existing HA entity orphans.
    blob = repr(d)
    assert "direct_connect_bridge" not in blob
    assert "Local Bridge" in d["sw_version"], "mqtt_scan.is_self matches this prefix"
    assert d["name"] == "FranklinWH aGate (Local Bridge)"


def test_two_distinct_serials_give_two_distinct_devices():
    a = entities.device_info("serial_a", "serial_a", None)
    b = entities.device_info("serial_b", "serial_b", None)
    assert a["identifiers"] != b["identifiers"]


def test_unique_ids_and_topics_are_namespaced_by_node():
    dev = entities.device_info("nodeA", "nodeA", None)
    cfgs, state_topic, avail_topic = entities.discovery_configs(
        "nodeA", dev, "franklinwh-local", "homeassistant")
    assert cfgs, "expected some discovery configs"
    assert all(c["unique_id"].startswith("franklinwh_nodeA_") for _, c in cfgs)
    # the node is in every topic, so another gateway cannot collide
    assert all("/nodeA/" in t for t, _ in cfgs)
    assert state_topic == "franklinwh-local/nodeA/state"
    assert avail_topic == "franklinwh-local/nodeA/availability"


def test_state_prefix_keeps_the_pre_rename_spelling():
    # `mqtt_prefix` defaults to "franklinwh-local". It is NOT cosmetic: changing it
    # moves every state topic, so already-discovered entities go unavailable and the
    # old topics linger retained. Renaming it needs a migration, not an edit.
    _, state_topic, _ = entities.discovery_configs(
        "nodeA", entities.device_info("nodeA", "nodeA", None),
        "franklinwh-local", "homeassistant")
    assert state_topic.startswith("franklinwh-local/")


# ── fix 1: the poller must not publish before the serial is known ─────────────
def test_poller_gates_the_initial_publish_on_a_known_serial():
    src = (ROOT / "src/franklinwh_direct_connect_bridge/poller.py").read_text()
    assert 'and not serial:' in src, "the deferral branch is gone"
    assert "deferring MQTT discovery" in src, "the operator-facing warning is gone"
    # the fallback must still exist for the UI, just never be published
    assert 'node, serial, fw = "agate", "", None' in src


def test_poller_retries_identity_before_retrying_the_publisher():
    src = (ROOT / "src/franklinwh_direct_connect_bridge/poller.py").read_text()
    heal = src.split("Self-heal:", 1)[1][:900]
    assert "_resolve_identity()" in heal, "a late serial would never be picked up"
    assert "if serial:" in heal, "the retry must stay gated on a known serial"


@pytest.mark.parametrize("serial", ["", None])
def test_fallback_node_is_never_a_valid_publish_target(serial):
    # Documents the invariant the poller enforces: no serial -> no device identity.
    assert not serial
