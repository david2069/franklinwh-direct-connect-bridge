"""Owner 2026-11-13: the panel left in the background in the Home Assistant app came back
as "404: Not Found". Under ingress, Home Assistant's ingress session expires while the app
is in the background, so the next poll gets 401 from Home Assistant (never from the
bridge: ingress is trusted). The 401 handler then sent the page to the absolute
``/signin``, which is Home Assistant's origin, where there is no such page. Under ingress a
401 is Home Assistant's to renew (its panel re-validates the session), so the page stays;
and the sign-in links are relative, so they never leave the bridge."""
import pathlib
import re

PKG = pathlib.Path(__file__).resolve().parents[1] / "src" / "franklinwh_direct_connect_bridge"
IDX = (PKG / "templates" / "index.html").read_text()
SET = (PKG / "static" / "js" / "settings_tab.js").read_text()


def test_401_under_ingress_does_not_leave_the_panel():
    i = IDX.index("const f = window.fetch;")
    hook = IDX[i:IDX.index("})();", i)]
    assert "/api/hassio_ingress/" in hook          # the guard
    assert "r.status === 401" in hook


def test_no_absolute_signin_links():
    for text in (IDX, SET):
        assert not re.search(r"""(href|location)\s*=\s*['"`]/signin""", text)
