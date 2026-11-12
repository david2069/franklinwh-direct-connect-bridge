"""Customise (#585, as the Modbus Bridge): one dialog for the top bar, the navbar and the
Dashboard cards. Rows drag by a handle (pointer events, so a finger works), keep finger-
sized up/down arrows as the fallback, and have switches. Saved at once, under the same
storage keys as before; Undo and Reset are inside the dialog. The Cards panel is gone."""
import pathlib
import re

PKG = pathlib.Path(__file__).resolve().parents[1] / "src" / "franklinwh_direct_connect_bridge"
T = PKG / "templates"
DIALOG = (T / "partials" / "customise.html").read_text()
JS = (PKG / "static" / "js" / "customise.js").read_text()
APP = (PKG / "static" / "js" / "app.js").read_text()
TOPBAR = (T / "partials" / "topbar.html").read_text()
DASH = (T / "tabs" / "dashboard.html").read_text()
INDEX = (T / "index.html").read_text()


def test_one_dialog_with_three_sections():
    assert '{% include "partials/customise.html" %}' in INDEX
    assert "static/js/customise.js" in INDEX
    assert 'data-testid="customise-dialog"' in DIALOG
    for sec in ("topbar", "nav", "cards"):
        assert f"customise-tab-' + t[0]" in DIALOG and f"'{sec}'" in DIALOG


def test_rows_drag_by_handle_with_arrows_and_switches():
    assert re.search(r'@pointerdown="[^"]*dragStart\(\$event', DIALOG) and 'data-testid="customise-handle"' in DIALOG
    assert "@pointermove.window" in DIALOG and "@pointerup.window" in DIALOG
    assert "touch-none" in DIALOG                       # a finger drag doesn't scroll
    assert 'data-testid="customise-up"' in DIALOG and 'data-testid="customise-down"' in DIALOG
    assert 'role="switch"' in DIALOG and 'type="checkbox"' not in DIALOG
    assert "setPointerCapture" in JS and "elementFromPoint" in JS


def test_saved_at_once_with_undo_and_reset_in_the_dialog():
    assert "Saved automatically" in DIALOG
    assert 'data-testid="customise-undo"' in DIALOG and 'data-testid="customise-reset"' in DIALOG
    assert "toast(" not in JS
    for key in ("fwh-local-nav", "fwh-local-topbar", "fwh-local-dash-cards", "fwh-local-dash-order"):
        assert key in APP                                # the same keys as before
    assert re.search(r"custSnapshot\(\)\s*\{", APP) and re.search(r"undoCustomise\(\)\s*\{", APP)


def test_the_cards_panel_is_gone_and_its_button_opens_the_dialog():
    assert "dashCardsOpen" not in DASH and "dashCardsOpen" not in TOPBAR
    assert "openCustomise('cards')" in TOPBAR
    assert "openCustomise('topbar')" in TOPBAR           # from the gear


def test_the_gear_keeps_theme_only():
    assert "['nav','Navbar']" not in TOPBAR and "['topbar','Top bar']" not in TOPBAR
    assert "moveTopbarItem(" not in TOPBAR and "moveNavItem(" not in TOPBAR
