"""Power Flow card (owner, 2026-11-07): one row per source with a word for what it is doing,
like the Modbus Bridge's, and a Now / Today toggle in the card for today's kWh."""
import pathlib

SRC = pathlib.Path(__file__).resolve().parents[1] / "src/franklinwh_direct_connect_bridge"
DASH = (SRC / "templates/tabs/dashboard.html").read_text()
APP_JS = (SRC / "static/js/app.js").read_text()


def _card():
    i = DASH.index("<!-- Power flow")
    return DASH[i:DASH.index("<!-- Battery (real local fields", i)]


def test_each_row_says_what_the_flow_is_doing():
    card = _card()
    for kind in ("solar", "home", "battery", "grid"):
        assert f"$store.app.flowText('{kind}'" in card, kind


def test_the_card_toggles_between_now_and_today():
    card = _card()
    assert "$store.app.setFlowView('now')" in card and "$store.app.setFlowView('today')" in card
    for k in ("solar", "home", "charged", "discharged", "grid_in", "grid_out"):
        assert f"$store.app.energyToday.{k}" in card, k
    assert "fwh-local-flow-view" in APP_JS                   # the choice is remembered


def _flow_text_fn():
    i = APP_JS.index("flowText(kind, w) {")
    return APP_JS[i:APP_JS.index("\n    },", i) + 6]


def test_the_words_follow_the_sign_conventions():
    # grid_w > 0 is import; battery_w > 0 is discharge; null says nothing.
    fn = _flow_text_fn()
    assert "if (w == null) return '';" in fn
    assert "grid: ['Importing', 'Exporting']" in fn
    assert "battery: ['Discharging', 'Charging']" in fn
    assert "solar: ['Generating', 'Idle']" in fn and "home: ['Consuming', 'Idle']" in fn
    assert "return w > 0 ? pos : (w < 0 ? neg : 'Idle');" in fn
