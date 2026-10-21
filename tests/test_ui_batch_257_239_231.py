"""UI batch: Guide links (#257), Logs short source names (#239), disclaimer fit (#231)."""

import logging
import re
from pathlib import Path

from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import app as app_module, logbuffer

TPL = Path(app_module.__file__).parent / "templates"
DOCS = "https://david2069.github.io/franklinwh-direct-connect-bridge/"
GUIDE = DOCS + "guide/"


def _page():
    return TestClient(app_module.create_app()).get("/").text


# -- #257: Guide opens the bridge's published docs directly --------------------------

def test_sidebar_and_more_sheet_link_straight_to_the_bridge_docs():
    html = _page()
    for url in (DOCS, GUIDE):
        # sidebar + More sheet + Settings card, each opened outside the add-on
        assert len(re.findall(rf'href="{re.escape(url)}" target="_blank" rel="noopener"', html)) >= 3
    assert "franklinwh-direct-connect-api/" not in html   # the library's site, not ours


def test_no_intermediate_guide_panel_remains():
    for p in TPL.rglob("*.html"):
        assert "openGuide" not in p.read_text(), p


def test_api_guide_points_at_the_bridge_site(monkeypatch):
    monkeypatch.setenv("FWH_DOCS_DIR", "/nonexistent-docs-dir")
    body = TestClient(app_module.create_app()).get("/api/guide").json()
    assert body["published_url"] == DOCS
    assert body["user_guide_url"] == GUIDE


# -- #239: Logs show a short module name ---------------------------------------------

def test_short_source_names():
    s = logbuffer.short_source
    assert s("franklinwh_direct_connect_bridge") == "bridge"
    assert s("franklinwh_direct_connect_bridge.poller") == "poller"
    assert s("franklinwh_direct_connect_bridge.a.b") == "a.b"
    assert s("franklinwh_modbus.controller") == "modbus.controller"
    assert s("uvicorn.access") == "uvicorn.access"
    assert s(None) == ""


def test_logs_api_carries_short_and_full_name():
    c = TestClient(app_module.create_app())
    logbuffer.clear()
    logging.getLogger("franklinwh_direct_connect_bridge.poller").warning("x")
    top = c.get("/api/logs?limit=1").json()["entries"][0]
    assert top["name"] == "franklinwh_direct_connect_bridge.poller"
    assert top["short"] == "poller"


def test_logs_cell_shows_short_name_with_full_name_tooltip():
    t = (TPL / "tabs/logs.html").read_text()
    assert ':title="e.name" x-text="e.short || e.name"' in t
    assert "hidden sm:inline\" x-text=\"e.name\"" not in t   # shown on phones too


# -- #231: the disclaimer fits a phone screen ----------------------------------------

def test_disclaimer_scrolls_and_keeps_the_button_in_view():
    html = (TPL / "index.html").read_text()
    d = html[html.index("First-connection legal disclaimer"):html.index("Toast notifications")]
    assert "max-height:calc(100dvh" in d
    assert "overflow-y-auto min-h-0" in d                 # the text scrolls
    assert d.count("shrink-0\" style=\"border-color") >= 2  # header + action row never shrink
    assert "|| 'guide/'" not in d
