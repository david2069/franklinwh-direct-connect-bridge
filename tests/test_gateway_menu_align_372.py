"""#372: the top-bar gateway menu was always right-aligned to the selector and 18 rem
wide. With the selector near the content's left edge (Dashboard, sidebar open) the menu
reached left past it and its names were cut off under the sidebar. It now opens
left-aligned when there is no room to the left, and never wider than a phone screen."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src/franklinwh_direct_connect_bridge"
APP_JS = (ROOT / "static/js/app.js").read_text()
TOPBAR = (ROOT / "templates/partials/topbar.html").read_text()


def _gw_menu():
    i = TOPBAR.index("<!-- Gateway selector")
    return TOPBAR[i:TOPBAR.index("<!-- Every gateway at a glance", i)]


def test_menu_side_is_chosen_not_fixed():
    menu = _gw_menu()
    assert '@click="$store.app.toggleGwMenu($el)"' in menu
    assert ":class=\"$store.app.gwMenuLeft ? 'left-0' : 'right-0'\"" in menu
    assert "absolute right-0" not in menu


def test_menu_fits_a_phone():
    assert "max-w-[calc(100vw-2rem)]" in _gw_menu()


def test_toggle_measures_room_to_the_left():
    i = APP_JS.index("toggleGwMenu(btn)")
    body = APP_JS[i:APP_JS.index("\n    },", i)]
    assert "getBoundingClientRect()" in body and "closest('header')" in body
    assert "this.gwMenuLeft =" in body and "this.gwMenuOpen = !this.gwMenuOpen" in body
