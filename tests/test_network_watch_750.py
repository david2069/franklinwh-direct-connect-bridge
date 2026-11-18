"""#750: the Network tab's Watch button used ``watching`` (and the loop ``latHistory`` /
``watchTick``) without declaring them in networkTab()'s data, so loading the tab threw
"watching is not defined"."""
import pathlib
import re

PKG = pathlib.Path(__file__).resolve().parents[1] / "src" / "franklinwh_direct_connect_bridge"


def test_watch_state_is_declared_in_the_tab_data():
    js = (PKG / "static" / "js" / "network_tab.js").read_text()
    html = (PKG / "templates" / "tabs" / "network.html").read_text()
    assert "watching" in html and "toggleWatch()" in html
    for key, init in (("watching", "false"), ("latHistory", r"\[\]"), ("watchTick", "0")):
        assert re.search(rf"^\s+{key}: {init},", js, re.M), key
