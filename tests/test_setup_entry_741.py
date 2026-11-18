"""Setup entry choice (#741, owner 2026-11-18): the setup list always shows three ways in at
the top — Automatic, Mock (demo) and Custom (advanced). Custom is the setup list itself,
unchanged; the first-run doors stay as they are."""
import re
from pathlib import Path

from franklinwh_direct_connect_bridge import setup_wizard

ROOT = Path(__file__).resolve().parents[1] / "src/franklinwh_direct_connect_bridge"
HTML = (ROOT / "templates/partials/setup_wizard.html").read_text()
JS = (ROOT / "static/js/setup_wizard.js").read_text()


def _hub() -> str:
    start = HTML.index("step === 'hub'")
    return HTML[start:HTML.index("</template>\n        </div>", start)]


def test_the_list_opens_with_three_entry_cards_in_order():
    hub = _hub()
    ids = re.findall(r'data-testid="setup-entry-(\w+)"', hub)
    assert ids == ["automatic", "mock", "custom"]
    assert hub.index('data-testid="setup-entry-custom"') < hub.index('data-testid="setup-task"')
    for label in ("Automatic", "Mock", "Custom"):
        assert f">{label}" in hub, label


def test_automatic_and_mock_start_the_existing_paths():
    hub = _hub()
    assert "startAutomatic()" in hub and "startMock()" in hub
    auto = JS[JS.index("startAutomatic()"):]
    assert "intent = 'hardware'" in auto[:400] and "_autoNext" in auto[:400]
    mock = JS[JS.index("startMock()"):]
    assert "intent = 'demo'" in mock[:400] and "go('hardware')" in mock[:400]


def test_custom_is_the_list_unchanged():
    hub = _hub()
    assert 'data-testid="setup-list"' in hub
    assert "showList()" in hub
    # the list's tasks and the "Start again" link are still there
    assert "tasksIn(g[0])" in hub and "Start again from the first steps" in hub
    assert len(setup_wizard.tasks(cloud=False)) == len(setup_wizard._TASKS)


def test_the_first_run_doors_are_unchanged():
    assert "Connect my FranklinWH aGate" in HTML
    assert "Explore with a mock gateway" in HTML
    assert "I'll set it up myself" in HTML
