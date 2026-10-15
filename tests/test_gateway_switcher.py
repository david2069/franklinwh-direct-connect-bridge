"""The gateway switcher shows, per gateway, its operating mode and battery direction.

Owner, 2026-10-15: on a multi-gateway site the switcher is where you choose between
gateways, so it is the one place their differences must be visible without selecting each
in turn.

These are text assertions on the controller and the template — weak, but the alternative is
no coverage at all for a view with no Python behind it. The logic that matters (what counts
as charging, what an absent reading means) is pinned by reading the same source the top-bar
pill uses.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src/franklinwh_direct_connect_bridge"


def _app_js():
    return (ROOT / "static/js/app.js").read_text()


def _topbar():
    return (ROOT / "templates/partials/topbar.html").read_text()


def test_mode_tag_covers_the_three_modes():
    js = _app_js()
    body = js[js.index("modeTag(name)"):js.index("flowDir(g)")]
    for tag in ("'SELF'", "'TOU'", "'EMGY'"):
        assert tag in body
    # A site-specific TOU tariff name must not be forced into one of the three silently —
    # there is a fallback that shows what was actually reported.
    assert "slice(0, 6)" in body


def test_direction_comes_from_the_run_status_enum():
    js = _app_js()
    body = js[js.index("flowDir(g)"):js.index("get selectedGatewayLabel()")]
    assert "rs === 1" in body and "'charge'" in body        # 1 = Charging
    assert "rs === 2" in body and "'discharge'" in body     # 2 = Discharging
    # Standby, the off-grid codes and an absent reading all mean "no arrow".
    assert "return ''" in body


def test_switcher_rows_render_mode_and_direction():
    html = _topbar()
    rows = html[html.index('x-for="g in $store.app.gateways"'):]
    assert "$store.app.modeTag(g.mode)" in rows
    assert "$store.app.flowDir(g) === 'charge'" in rows
    assert "$store.app.flowDir(g) === 'discharge'" in rows
    # Unknown is shown as nothing, not as a default mode or a neutral arrow.
    assert 'x-show="g.mode"' in rows


def test_direction_icons_are_svg_not_emoji():
    """UI policy: inline SVG icons only."""
    html = _topbar()
    rows = html[html.index('x-for="g in $store.app.gateways"'):]
    assert "<title>Charging</title>" in rows and "<title>Discharging</title>" in rows
    for glyph in ("⬆", "⬇", "🔋", "⚡"):
        assert glyph not in rows
