"""Sign-in page (owner 2026-11-20): it shows the bridge's version and links to the
documentation, GitHub Discussions and Issues, each opening in a new tab."""
import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import __version__, app as app_module, tls

REPO = "https://github.com/david2069/franklinwh-direct-connect-bridge"


@pytest.fixture
def page(monkeypatch):
    monkeypatch.setattr(tls, "running", lambda: True)
    monkeypatch.setitem(tls.status, "port", 8102)
    c = TestClient(app_module.create_app(), base_url="https://bridge.lan:8102")
    r = c.get("/signin")
    assert r.status_code == 200
    return r.text


def test_the_version_is_shown(page):
    assert f"Version {__version__}" in page


@pytest.mark.parametrize("href", [
    "https://david2069.github.io/franklinwh-direct-connect-bridge/",
    f"{REPO}/discussions",
    f"{REPO}/issues",
])
def test_the_links(page, href):
    tag = page.split(f'href="{href}"', 1)[1].split(">", 1)[0]
    assert 'target="_blank"' in tag and 'rel="noopener"' in tag
