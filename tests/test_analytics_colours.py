"""Owner, 2026-11-10: Battery discharged and SoC were almost the same green. A colour per
series for Local and Cloud, remembered in this browser, with Dark and Light background
presets and Reset to defaults; SoC's default no longer looks like the battery's."""
import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "franklinwh_direct_connect_bridge"
JS = (SRC / "static" / "js" / "analytics_tab.js").read_text()
HTML = (SRC / "templates" / "tabs" / "analytics.html").read_text()


def _palette(name):
    body = JS[JS.index("const ANALYTICS_COLOURS"):][:2000]
    block = body[body.index(name + ": {"):]
    return dict(re.findall(r"(\w+): '(#[0-9a-f]{6})'", block[:block.index("}")]))


def test_defaults_and_both_presets_cover_every_series():
    keys = {"home", "solar", "battery_discharge", "battery_charge", "grid_import", "grid_export", "soc", "generator"}
    for name in ("defaults", "dark", "light"):
        assert set(_palette(name)) == keys, name


def _dist(a, b):
    ra, rb = (tuple(int(c[i:i + 2], 16) for i in (1, 3, 5)) for c in (a, b))
    return sum((x - y) ** 2 for x, y in zip(ra, rb)) ** .5


def test_soc_does_not_look_like_the_battery():
    for name in ("defaults", "dark", "light"):
        p = _palette(name)
        assert _dist(p["soc"], p["battery_discharge"]) > 150, name
        assert _dist(p["soc"], p["battery_charge"]) > 150, name


def test_colours_are_remembered_and_reach_both_charts():
    assert "'fwh-analytics-colours'" in JS
    assert "colourOf(" in JS and "applyCloudColours()" in JS
    assert "setProperty" in JS[JS.index("applyCloudColours() {"):][:400]
    vars_ = JS[JS.index("const ANALYTICS_CLOUD_VARS"):][:600]
    assert "soc: ['--ca-soc']" in vars_ and "'--ca-battery_discharge'" in vars_
    assert "m.color" not in HTML                        # chips take the picked colour
    assert "colourOf(m.key)" in HTML


def test_the_dialog_has_a_picker_per_series_presets_and_reset():
    assert 'aria-label="Chart colours"' in HTML and 'type="color"' in HTML
    for b in ("Dark background", "Light background", "Reset to defaults"):
        assert b in HTML
    assert "Colours…" in HTML                           # opened from the Chart ▾ menu
