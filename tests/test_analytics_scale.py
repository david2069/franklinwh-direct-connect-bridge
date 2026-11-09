"""Owner, 2026-11-10: Local and Cloud charts should almost always have the same size and
scale. Both are 380 px tall, and Local's power/energy axis uses Cloud's rule: from
min(0, data) to max(0, data) in four nice steps (1, 2, 5 × 10ⁿ)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "franklinwh_direct_connect_bridge"
JS = (SRC / "static" / "js" / "analytics_tab.js").read_text()
HTML = (SRC / "templates" / "tabs" / "analytics.html").read_text()


def test_the_cloud_panel_is_as_tall_as_the_local_chart():
    assert 'style="height:380px"' in HTML
    mount = JS[JS.index("FWHCloudAnalytics.mount("):][:400]
    assert "height: 380" in mount


def test_local_y_axis_uses_the_clouds_rule():
    body = JS[JS.index("function analyticsYRange("):][:900]
    assert "Math.min(0" in body and "Math.max(0" in body and "/ 4" in body
    assert "m <= 1 ? 1 : m <= 2 ? 2 : m <= 5 ? 5 : 10" in body       # the cloud's nice()
    render = JS[JS.index("render() {"):][:6000]
    assert "analyticsYRange(" in render and "stepSize" in render


def test_the_cloud_extra_has_the_height_option():
    assert "franklinwh-ha-cloud-analytics==0.1.23" in (ROOT / "pyproject.toml").read_text()
