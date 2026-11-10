"""System view and the top-bar menus on a phone (owner, 2026-11-07, iPhone screenshots).

The gateway and mode menus opened partly off-screen over the page, with nothing to show
they were menus; the System view's options took more room than its diagram; its own
gateway buttons repeated the top bar's picker; and an empty gap sat above it.
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src/franklinwh_direct_connect_bridge"
TOPBAR = (SRC / "templates/partials/topbar.html").read_text()
INDEX = (SRC / "templates/index.html").read_text()
APP_JS = (SRC / "static/js/app.js").read_text()
CSS = (SRC / "static/css/design-system.css").read_text()


def test_the_system_view_follows_the_top_bar_picker_only():
    assert "gatewayChips: false" in INDEX


def test_the_pinned_system_view_has_the_phone_layout():
    # 0.2.4: Options fold away on phones, opens fitted, follows the top bar's height.
    pin = (ROOT / "pyproject.toml").read_text()
    assert '"franklinwh-system-view==0.3.0"' in pin


def test_the_top_bar_menus_stay_on_a_phone_screen():
    for marker in ("<!-- Gateway selector", "<!-- Operating mode —"):
        i = TOPBAR.index(marker)
        assert "tb-menu" in TOPBAR[i:i + 1500], marker
    m = re.search(r"@media \(max-width: 639px\)\s*\{[^}]*\.tb-menu\s*\{([^}]*)\}", CSS)
    assert m, "no phone rule for .tb-menu"
    rule = m.group(1)
    assert "position: fixed" in rule and "left: 1rem" in rule and "right: 1rem" in rule
    assert "var(--topbar-h" in rule


def test_an_open_menu_dims_the_page_on_a_phone_and_a_tap_closes_it():
    i = TOPBAR.index("<!-- Menu backdrop")
    el = TOPBAR[i:TOPBAR.index(">", TOPBAR.index("<div", i))]
    assert 'x-show="$store.app.anyTopbarMenuOpen"' in el
    assert '@click="$store.app.closeTopbarMenus()"' in el
    assert "sm:hidden" in el and "fixed inset-0" in el


def test_scrolling_closes_the_menus():
    assert "closeTopbarMenus()" in APP_JS
    i = APP_JS.index("closeTopbarMenus() {")
    body = APP_JS[i:APP_JS.index("\n    },", i)]
    for flag in ("gwMenuOpen", "modeMenuOpen", "topbarPrefsOpen"):
        assert f"this.{flag} = false" in body
    i = APP_JS.index("addEventListener('scroll'")
    assert "this.closeTopbarMenus()" in APP_JS[i:i + 300]
