"""Automatic setup (#741, owner 2026-11-18): one aGate and its aPower. Find or enter the
aGate, connect and verify, then — only where not already done — link Home Assistant
(asked early, skippable), sign in to the FranklinWH cloud, turn on the Modbus client and
publish to Home Assistant, each with a Skip; it ends on a summary. The first-run doors keep
their own path."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src/franklinwh_direct_connect_bridge"
HTML = (ROOT / "templates/partials/setup_wizard.html").read_text()
JS = (ROOT / "static/js/setup_wizard.js").read_text()


def _fn(name: str) -> str:
    i = JS.index(f"    {name}(") if f"    {name}(" in JS else JS.index(f"    async {name}(")
    j = JS.index("\n    },", i)
    return JS[i:j]


def test_automatic_runs_the_steps_in_the_approved_order():
    m = re.search(r"AUTO_STEPS:\s*\[([^\]]*)\]", JS)
    assert m, "AUTO_STEPS missing"
    steps = re.findall(r"'(\w+)'", m.group(1))
    assert steps == ["timezone", "find", "confirm", "halink", "cloud", "modbus", "publish",
                     "summary"]


def test_a_step_already_done_is_passed_over():
    done = _fn("_autoDone")
    for step, fact in (("halink", "home_assistant"), ("cloud", "cloud"), ("publish", "mqtt")):
        assert f"'{step}'" in done and f"'{fact}'" in done, step
    assert "this.mb.enabled" in done             # Modbus client already on
    assert "createdIds" in done                  # a gateway added now still asks to publish
    nxt = _fn("_autoNext")
    assert "_autoDone" in nxt and "'summary'" in nxt


def test_start_automatic_reads_the_facts_then_starts():
    start = _fn("startAutomatic")
    assert "this.auto = true" in start
    assert "loadTasks" in start and "loadModbus" in start
    assert "_autoNext" in start


def test_the_first_run_paths_are_unchanged_when_not_automatic():
    adv = _fn("_advance")
    assert "this.auto" in adv
    # the hard-wired first-run order still applies outside Automatic
    assert "this._advance('find', 'cloud')" in JS
    assert "this._advance('cloud', 'confirm')" in JS
    assert "this._advance('confirm', 'publish')" in JS
    assert "this.go(this.intent === 'demo' ? 'demo' : 'find')" not in JS
    assert "this._advance('timezone', this.intent === 'demo' ? 'demo' : 'find')" in JS
    # Mock never sees the HA link, Modbus or summary steps
    assert "startMock" in JS and "this.auto = false" in _fn("startMock")


def test_the_ha_link_step_is_early_and_skippable():
    tpl = HTML[HTML.index("step === 'halink'"):]
    tpl = tpl[:tpl.index("</template>")]
    for f in ('x-model="hal.base_url"', 'x-model="hal.token"', "testHaLink()", "saveHaLink()"):
        assert f in tpl, f
    assert 'type="password"' in tpl
    save = _fn("saveHaLink")
    assert "api/ha/instances" in save and "is_default: true" in save
    assert "api/ha/test" in _fn("testHaLink")
    label = _fn("get nextLabel") if "    get nextLabel(" in JS else JS[JS.index("get nextLabel"):]
    assert "'halink'" in label[:1500]


def test_summary_lists_each_part_and_points_to_custom():
    tpl = HTML[HTML.index("step === 'summary'"):]
    tpl = tpl[:tpl.index("<!-- The setup list")]
    assert 'data-testid="setup-summary"' in tpl
    assert "autoSummary" in tpl and "toHub()" in tpl and "Custom" in tpl
    rows = _fn("get autoSummary") if "    get autoSummary(" in JS else JS[JS.index("get autoSummary"):][:1500]
    for part in ("aGate", "Home Assistant link", "FranklinWH cloud", "Modbus client",
                 "Publish to Home Assistant"):
        assert part in rows, part


def test_more_than_one_unit_is_said_not_guessed():
    tpl = HTML[HTML.index("step === 'summary'"):]
    tpl = tpl[:tpl.index("<!-- The setup list")]
    assert 'data-testid="setup-multi-unit"' in tpl
    multi = JS[JS.index("get multiUnit"):][:1500]
    assert "apowers" in multi and "agates" in multi
