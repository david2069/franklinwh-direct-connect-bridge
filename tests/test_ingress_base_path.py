"""The UI must load its own assets when served through Home Assistant ingress.

Reported 2026-10-15 from a live add-on install: the panel rendered as unstyled HTML with
oversized raw SVGs. Every asset and API call in this UI is RELATIVE and resolves against
<base href>, which was hardcoded to "/" — so under ingress
(/api/hassio_ingress/<token>/) they all resolved to the root of the Home Assistant host,
outside ingress, and 404ed.
"""
import re

from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import app as app_module, config, db, environment
from franklinwh_direct_connect_bridge.db import MetricsStore

INGRESS = "/api/hassio_ingress/abc123TOKEN"


def _client(tmp_path, monkeypatch):
    monkeypatch.setattr(environment, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "_settings", None)
    monkeypatch.setattr(db, "get_store", lambda s: MetricsStore(str(tmp_path / "m.db")))
    return TestClient(app_module.create_app())


def _base_href(html: str) -> str:
    m = re.search(r'<base href="([^"]*)"', html)
    assert m, "the page has no <base href> at all"
    return m.group(1)


def test_base_href_follows_the_ingress_path(tmp_path, monkeypatch):
    r = _client(tmp_path, monkeypatch).get("/", headers={"X-Ingress-Path": INGRESS})
    assert r.status_code == 200
    assert _base_href(r.text) == INGRESS + "/"


def test_a_trailing_slash_is_not_doubled(tmp_path, monkeypatch):
    r = _client(tmp_path, monkeypatch).get("/", headers={"X-Ingress-Path": INGRESS + "/"})
    assert _base_href(r.text) == INGRESS + "/"


def test_standalone_still_serves_the_root(tmp_path, monkeypatch):
    """No ingress header — the plain Docker install must be unchanged."""
    r = _client(tmp_path, monkeypatch).get("/")
    assert _base_href(r.text) == "/"


def test_a_header_that_is_not_a_path_is_ignored(tmp_path, monkeypatch):
    """Anything that is not an absolute path would break every asset URL."""
    r = _client(tmp_path, monkeypatch).get("/", headers={"X-Ingress-Path": "evil.example.com"})
    assert _base_href(r.text) == "/"


def test_assets_are_relative_so_the_base_tag_actually_governs_them(tmp_path, monkeypatch):
    """If anything hardcodes /static or /api, fixing <base> fixes nothing for it."""
    r = _client(tmp_path, monkeypatch).get("/", headers={"X-Ingress-Path": INGRESS})
    assert 'href="static/css/' in r.text and 'src="static/js/' in r.text
    assert 'src="/static/' not in r.text and 'href="/static/' not in r.text


# --- the add-on's own presentation -----------------------------------------------------------
# Reported 2026-10-15 from the live install: the add-on showed the generic puzzle-piece
# icon, and its description was clipped mid-phrase in the store listing.

def test_the_addon_ships_an_icon_and_a_logo():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    for name, size in (("icon.png", (128, 128)), ("logo.png", (250, 150))):
        f = root / name
        assert f.is_file(), f"{name} is missing — the Supervisor falls back to a puzzle piece"
        head = f.read_bytes()[:24]
        assert head[:8] == b"\x89PNG\r\n\x1a\n"
        width = int.from_bytes(head[16:20], "big")
        height = int.from_bytes(head[20:24], "big")
        assert (width, height) == size


def test_the_store_description_is_short_enough_not_to_be_clipped():
    import re
    from pathlib import Path
    cfg = (Path(__file__).resolve().parents[1] / "config.yaml").read_text()
    m = re.search(r'^description:\s*"([^"]+)"', cfg, re.M)
    assert m, "config.yaml has no description"
    assert len(m.group(1)) <= 75, "the add-on store clips the description to two short lines"
