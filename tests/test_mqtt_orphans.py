"""Classifying retained HA-discovery configs into ours-live / ours-orphaned / foreign.

The purge publishes an empty retained payload to every topic this says is an orphan,
so a false positive deletes a working integration's entities. The broker is shared:
the Modbus bridge and FWHAI publish into the same ``franklinwh_*`` namespace. These
tests exist to keep the ownership test conservative.

Shapes here mirror a real capture from the dev broker (467 retained configs, 4 of 21
nodes ours), with identifiers anonymised.
"""
import json

from franklinwh_direct_connect_bridge.publish import mqtt_scan

PREFIX = "homeassistant"


def _cfg(node, sw, name="FranklinWH aGate (Local Bridge)"):
    return json.dumps({
        "name": "State of Charge",
        "unique_id": f"franklinwh_{node}_soc",
        "device": {"identifiers": [f"franklinwh_{node}"], "name": name, "sw_version": sw},
    }).encode()


def _ours(node, ver="0.2.0", fw=None):
    return _cfg(node, f"Local Bridge v{ver}" + (f" · aGate {fw}" if fw else ""))


def _msgs(spec):
    """spec: {node: (payload, n_entities)} -> {topic: payload}"""
    out = {}
    for node, (payload, n) in spec.items():
        for i in range(n):
            out[f"{PREFIX}/sensor/{node}/key{i}/config"] = payload
    return out


def test_live_node_is_kept_and_orphans_are_found():
    msgs = _msgs({
        "serial0001": (_ours("serial0001", fw="V12R02"), 21),   # live
        "agate":      (_ours("agate"), 21),                     # the old fallback
        "mockaaaa":   (_ours("mockaaaa", fw="V12R02"), 21),      # torn-down demo gw
    })
    r = mqtt_scan.find_orphans(msgs, ["serial0001"], PREFIX)
    assert r["ok"]
    assert r["counts"]["live"] == 21
    assert r["counts"]["orphaned"] == 42
    assert r["counts"]["orphaned_devices"] == 2
    assert {g["node"] for g in r["orphans"]} == {"agate", "mockaaaa"}
    assert all("/serial0001/" not in t for t in r["orphan_topics"]), \
        "the live gateway's topics must never be queued for deletion"


def test_another_integrations_entities_are_never_touched():
    # The Modbus bridge and FWHAI publish franklinwh_* identifiers with the aGate's
    # own firmware as sw_version. 383 of the 467 configs on the real broker are theirs.
    msgs = _msgs({
        "serial0001": (_ours("serial0001"), 5),
        "modbusnode": (_cfg("modbusnode", "V12R02B30D06", "FranklinWH aGate"), 69),
        "fwhainode":  (_cfg("fwhainode", "V12R02B85D00_250624 (FEM: v1.0.45)",
                            "FranklinWH aGate X-01-AU 0091"), 8),
    })
    r = mqtt_scan.find_orphans(msgs, ["serial0001"], PREFIX)
    assert r["counts"]["orphaned"] == 0, "nothing of ours is stale here"
    assert r["counts"]["foreign"] == 77
    assert not r["orphan_topics"]


def test_a_foreign_producer_on_an_unknown_node_is_foreign_not_orphan():
    # The trap: an unknown node that is NOT ours must be foreign, never purgeable.
    msgs = _msgs({"someoneelse": (_cfg("someoneelse", "Modbus Bridge v1.2"), 12)})
    r = mqtt_scan.find_orphans(msgs, ["serial0001"], PREFIX)
    assert r["counts"]["orphaned"] == 0
    assert r["counts"]["foreign"] == 12


def test_a_config_with_no_device_block_is_not_claimed():
    msgs = {f"{PREFIX}/sensor/x/y/config": json.dumps({"name": "franklinwh thing"}).encode()}
    r = mqtt_scan.find_orphans(msgs, [], PREFIX)
    assert r["counts"]["orphaned"] == 0


def test_already_cleared_and_unparseable_topics_are_skipped():
    msgs = {
        f"{PREFIX}/sensor/a/b/config": b"",            # already purged
        f"{PREFIX}/sensor/c/d/config": b"not json",    # not ours
    }
    r = mqtt_scan.find_orphans(msgs, [], PREFIX)
    assert r["counts"]["orphaned"] == 0
    assert not r["orphan_topics"]


def test_node_matching_is_case_insensitive():
    msgs = _msgs({"SERIAL0001": (_ours("SERIAL0001"), 3)})
    r = mqtt_scan.find_orphans(msgs, ["serial0001"], PREFIX)
    assert r["counts"]["orphaned"] == 0, "node ids are lowercased when published"


def test_empty_live_roster_does_not_make_everything_an_orphan_of_others():
    msgs = _msgs({"foreignnode": (_cfg("foreignnode", "V12R02B30D06"), 9)})
    r = mqtt_scan.find_orphans(msgs, [], PREFIX)
    assert r["counts"]["foreign"] == 9
    assert r["counts"]["orphaned"] == 0


def test_purge_refuses_when_the_broker_changed_since_the_dry_run(monkeypatch):
    monkeypatch.setattr(mqtt_scan, "scan_orphans",
                        lambda *a, **k: {"ok": True, "orphan_topics": ["a", "b"],
                                         "orphans": [], "counts": {"orphaned": 2}})
    r = mqtt_scan.purge_orphans(object(), ["n"], expect=5)
    assert r["ok"] is False
    assert "broker changed" in r["error"]


def test_purge_is_a_noop_when_there_is_nothing_to_clear(monkeypatch):
    monkeypatch.setattr(mqtt_scan, "scan_orphans",
                        lambda *a, **k: {"ok": True, "orphan_topics": [],
                                         "orphans": [], "counts": {"orphaned": 0}})
    r = mqtt_scan.purge_orphans(object(), ["n"], expect=0)
    assert r["ok"] and r["cleared"] == 0
