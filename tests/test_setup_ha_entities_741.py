"""Existing Home Assistant entities (#741, owner 2026-11-18). Before anything is published,
Automatic (and the setup list) shows what FranklinWH entities Home Assistant already has:
from the broker's retained discovery configs and, when HA is linked, from its registry.
The bridge may remove only its OWN leftovers, with confirmation; everything else is
reported, never touched. Richo's cloud integration (`franklin_wh`) gets an optional note
with what the bridge adds; Keep both hides it for good."""
import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import (app as app_module, config, db, environment,
                                              ha_entities, ha_instances, state)
from franklinwh_direct_connect_bridge.db import MetricsStore
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src/franklinwh_direct_connect_bridge"
HTML = (ROOT / "templates/partials/setup_wizard.html").read_text()
JS = (ROOT / "static/js/setup_wizard.js").read_text()

SERIAL = "TESTSERIAL0001"
ORPHAN = {"identifier": "franklinwh_oldserial", "node": "oldserial", "name": "aGate old",
          "sw_version": "Direct Connect Bridge v0.4.9", "ours": True, "entities": 41,
          "topics": ["t"] * 41}
MB = {"identifier": f"franklinwh_fwh_mb_{SERIAL.lower()}", "node": "", "name": "aGate",
      "sw_version": "Modbus Bridge v0.1.0", "ours": False, "entities": 60, "topics": [],
      "serial_number": SERIAL}
FWHAI = {"identifier": "franklinwh_x", "node": "", "name": "Other", "sw_version": "FWHAI 2.0",
         "ours": False, "entities": 12, "topics": []}


def inv(**kw):
    base = dict(broker={"ok": True, "orphans": [], "foreign": [], "live": []},
                registry=None, components=[], serials=[SERIAL], richo_dismissed=False,
                purge_ready=True)
    return ha_entities.inventory(**{**base, **kw})


def test_our_leftovers_can_be_removed_others_only_reported():
    out = inv(broker={"ok": True, "orphans": [ORPHAN], "foreign": [MB, FWHAI], "live": []})
    rows = {r["kind"]: r for r in out["rows"]}
    assert rows["ours_orphan"]["entities"] == 41 and rows["ours_orphan"]["action"] == "remove"
    others = [r for r in out["rows"] if r["kind"] == "other"]
    assert len(others) == 2 and all(r["action"] == "report" for r in others)
    assert {r["who"] for r in others} == {"Modbus Bridge v0.1.0", "FWHAI 2.0"}


def test_the_same_agate_and_a_second_modbus_writer_are_flagged():
    out = inv(broker={"ok": True, "orphans": [], "foreign": [MB], "live": []})
    assert out["other_same_agate"] is True and out["modbus_writer"] is True
    out = inv(broker={"ok": True, "orphans": [], "foreign": [FWHAI], "live": []})
    assert out["other_same_agate"] is False and out["modbus_writer"] is False


def test_registry_duplicates_and_unreachable_parts_are_said():
    reg = [{"identifiers": ["franklinwh_testserial0001"], "name": "aGate",
            "sw_version": "Direct Connect Bridge v0.5.52", "entities": 90, "dup2": 7}]
    out = inv(broker={"ok": False, "error": "cannot reach broker"}, registry=reg)
    dup = [r for r in out["rows"] if r["kind"] == "dup2"]
    assert dup and dup[0]["entities"] == 7 and dup[0]["action"] == "report"
    assert out["broker"]["checked"] is False and "broker" in out["broker"]["why"]
    assert out["registry"]["checked"] is True
    out = inv(registry=None)
    assert out["registry"]["checked"] is False


def test_removal_needs_publishing_on():
    out = inv(broker={"ok": True, "orphans": [ORPHAN], "foreign": [], "live": []},
              purge_ready=False)
    assert [r for r in out["rows"] if r["kind"] == "ours_orphan"][0]["action"] == "report"


def test_richo_note_is_optional_and_lists_what_the_bridge_adds():
    out = inv(components=["mqtt", "franklin_wh"])
    assert out["richo"]["show"] is True
    adds = out["richo"]["adds"]
    assert 3 <= len(adds) <= 5 and all(isinstance(a, str) and a for a in adds)
    assert inv(components=["mqtt", "franklin_wh"], richo_dismissed=True)["richo"]["show"] is False
    assert inv(components=["mqtt"])["richo"]["show"] is False


def test_the_registry_template_counts_franklinwh_devices_and_true_duplicates():
    t = ha_instances.FRANKLIN_DEVICES_TEMPLATE
    assert "integration_entities('mqtt')" in t and "franklin" in t
    assert "_2$" in t and "regex_replace" in t        # x_2 only when x exists too


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    st = MetricsStore(str(tmp_path / "m.db"))
    monkeypatch.setattr(environment, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "_settings", None)
    monkeypatch.setattr(db, "get_store", lambda s: st)
    monkeypatch.setattr(app_module, "discover_mqtt", lambda: {"found": False})
    state.reset_gateways()
    yield st
    state.reset_gateways()


def test_the_endpoint_reads_and_never_writes(ctx):
    c = TestClient(app_module.create_app())
    d = c.get("/api/setup/ha-entities").json()
    assert {"rows", "broker", "registry", "richo", "other_same_agate", "modbus_writer"} <= set(d)
    assert d["registry"]["checked"] is False         # no HA linked


def test_keep_both_is_remembered(ctx):
    c = TestClient(app_module.create_app())
    r = c.post("/api/setup/ha-entities/richo-note", json={"keep_both": True})
    assert r.status_code == 200
    assert ctx.get_config(ha_entities.RICHO_KEY, "") == "keep_both"


def test_the_wizard_runs_it_after_the_ha_link_and_lists_it():
    import re
    from franklinwh_direct_connect_bridge import setup_wizard
    steps = re.findall(r"'(\w+)'", re.search(r"AUTO_STEPS:\s*\[([^\]]*)\]", JS).group(1))
    assert steps.index("haentities") == steps.index("halink") + 1
    t = {x["id"]: x for x in setup_wizard.tasks()}
    assert t["ha_entities"]["group"] == "advanced" and t["ha_entities"]["inline"] == "haentities"
    tpl = HTML[HTML.index("step === 'haentities'"):]
    tpl = tpl[:tpl.index("<!-- Automatic (#741): what it left set up")]
    for s in ('data-testid="ha-entities-row"', 'data-testid="richo-note"', "Keep both",
              "Tell me more", "removeOrphans(", "haInv.richo.adds"):
        assert s in tpl, s


def test_modbus_and_publish_default_to_skip_when_another_integration_is_there():
    mb = HTML[HTML.index("step === 'modbus'"):]
    mb = mb[:mb.index("</template>")]
    assert "haInv.modbus_writer" in mb
    pub = HTML[HTML.index("step === 'publish'"):]
    pub = pub[:pub.index("</template>")]
    assert "haInv.other_same_agate" in pub
    assert 'data-testid="publish-other-integration"' in pub


# Owner 2026-11-20: detect whether richo's integration is still active and warn the user to
# disable it when they are ready; no takeover.

def test_richo_activity_says_how_many_entities_and_when_it_last_updated():
    out = inv(components=["franklin_wh"],
              richo_activity={"entities": 12, "last": "2026-11-20T08:00:00+00:00"})
    r = out["richo"]
    assert r["show"] and r["active"] is True
    assert r["entities"] == 12 and r["last_update"] == "2026-11-20T08:00:00+00:00"


def test_richo_activity_unread_is_still_a_note():
    r = inv(components=["franklin_wh"], richo_activity=None)["richo"]
    assert r["show"] and r["active"] is True and r["last_update"] is None


def test_richo_activity_template_reads_the_newest_report(monkeypatch):
    import io
    import json as _json
    sent = {}

    def fake(req, timeout):
        sent["body"] = _json.loads(req.data.decode())["template"]
        return io.BytesIO(b'{"entities": 3, "last": "2026-11-20T08:00:00+00:00"}')
    monkeypatch.setattr(ha_instances.urllib.request, "urlopen", fake)
    got = ha_instances.richo_activity("http://ha:8123", "tok")
    assert got == {"entities": 3, "last": "2026-11-20T08:00:00+00:00"}
    assert "integration_entities('franklin_wh')" in sent["body"] and "last_reported" in sent["body"]


def test_the_note_warns_to_disable_it_when_ready():
    tpl = HTML[HTML.index('data-testid="richo-note"'):]
    tpl = tpl[:tpl.index("</template>", tpl.index("Tell me more"))]
    # Richo's integration is set up in YAML (2026.3.0 has no config flow), so it is turned
    # off by removing its platform entries, not from Devices & services.
    for s in ("configuration.yaml", "platform: franklin_wh", "restart", "richoAgo(",
              "when you're ready"):
        assert s in tpl, s
    assert "keep your entity names and history" not in tpl
    assert "richoAgo(" in JS


def test_richo_set_up_in_yaml_is_seen():
    """Seen on the test VM 2026-11-20: a YAML-configured richo integration shows in HA's
    components as 'franklin_wh.sensor', not 'franklin_wh'."""
    assert inv(components=["mqtt", "franklin_wh.sensor"])["richo"]["show"] is True
    assert inv(components=["franklin_wh_other"])["richo"]["show"] is False
