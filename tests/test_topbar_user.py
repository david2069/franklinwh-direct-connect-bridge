"""The signed-in user in the top bar (owner 2026-11-20): username and role, with Sign out
for an account signed in on the HTTPS port. A Customise → Top bar item, on by default;
shown only when someone is signed in (Security on, or Home Assistant's sidebar)."""
from pathlib import Path

PKG = Path(__file__).resolve().parents[1] / "src" / "franklinwh_direct_connect_bridge"
APP_JS = (PKG / "static" / "js" / "app.js").read_text()
TOPBAR = (PKG / "templates" / "partials" / "topbar.html").read_text()


def test_it_is_a_top_bar_item_on_by_default():
    assert "{ id: 'user', label: 'Signed-in user', on: true }" in APP_JS


def test_it_shows_the_principal_and_signs_out():
    i = TOPBAR.index('data-testid="topbar-user"')
    block = TOPBAR[TOPBAR.rindex("<div", 0, i):TOPBAR.index("<!-- /topbar-user -->")]
    assert "$store.app.me" in block and "topbarShow('user')" in block
    assert "me.username" in block and "me.role" in block
    assert "$store.app.signOut()" in block and "me.via === 'session'" in block


def test_sign_out_ends_the_session():
    i = APP_JS.index("async signOut()")
    assert "api/auth/logout" in APP_JS[i:i + 300] and "signin" in APP_JS[i:i + 300]


def test_me_is_loaded_with_the_role():
    i = APP_JS.index("async _loadRoleTabs()")
    assert "this.me = " in APP_JS[i:i + 600]
