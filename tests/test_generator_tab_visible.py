"""#238: the Generator tab is always available, as in the FranklinWH app.

It was hidden unless the bridge inferred a generator, which also hid the only switch that
turns the generator feature on. The bridge cannot know what is wired up, so nothing in the
UI may claim a generator is or is not installed."""
import pathlib
import re

SRC = pathlib.Path(__file__).resolve().parents[1] / "src/franklinwh_direct_connect_bridge"
APP_JS = (SRC / "static/js/app.js").read_text()
TAB = (SRC / "templates/tabs/generator.html").read_text()
TAB_JS = (SRC / "static/js/generator_tab.js").read_text()
DASH = (SRC / "templates/tabs/dashboard.html").read_text()


def _body(src, start):
    i = src.index(start)
    return src[i:src.index("\n    },", i)] if "{\n" in src[i:i + 200] else src[i:src.index("\n", i)]


def test_nav_never_filters_the_generator_tab():
    line = _body(APP_JS, "get navAvailable()")
    assert "generator" not in line and "filter" not in line, line


def test_the_tab_is_not_bounced_back_to_the_dashboard():
    body = _body(APP_JS, "async _loadGeneratorInstalled()")
    assert "setActiveTab" not in body


def test_dashboard_generator_metric_follows_the_feature_switch():
    assert 'x-show="$store.app.generatorEnabled"' in DASH
    assert "generatorInstalled" not in APP_JS + DASH


def test_no_installed_claims_in_the_tab_text():
    text = re.sub(r"<!--.*?-->", "", TAB, flags=re.S) + TAB_JS
    for claim in ("appears to be installed", "until a module is installed",
                  "physically installed", "No generator enabled or detected"):
        assert claim not in text, claim


def test_mode_buttons_are_gone():
    assert "setMode" not in TAB + TAB_JS
    assert "api/generator/mode" not in TAB_JS
