"""Location & Solar sits under Sites & Billing, right after Sites & Meters (owner,
2026-11-13, #582 follow-up): the location belongs to the site."""
import pathlib

from franklinwh_direct_connect_bridge import scheduler

PKG = pathlib.Path(__file__).resolve().parents[1] / "src" / "franklinwh_direct_connect_bridge"
HTML = (PKG / "templates" / "tabs" / "settings.html").read_text()


def _sub_of(i):
    """The settings sub-tab whose block holds position ``i``."""
    j = HTML.rfind("x-show=\"sub==='", 0, i)
    return HTML[j + len("x-show=\"sub==='"):HTML.index("'", j + len("x-show=\"sub==='"))]


def test_location_and_solar_is_under_sites_and_billing():
    i = HTML.index("<!-- ══ Location & Solar ══ -->")
    assert _sub_of(i) == "billing"
    sites = HTML.index("Sites &amp; Meters")
    tariffs = HTML.index("<!-- ══ Prices (#582)")   # the next section (the tariffs are on the meters now)
    assert sites < i < tariffs, "right after Sites & Meters"


def test_messages_point_to_the_new_place():
    assert "Sites & Billing → Location & Solar" in scheduler._SETUP_SOLAR
    assert "Integrations → Location & Solar" not in (PKG / "app.py").read_text()


def test_the_card_and_the_solar_tab_link_each_other():
    i = HTML.index("<!-- ══ Location & Solar ══ -->")
    card = HTML[i:HTML.index("<!-- ══ Prices (#582)")]
    assert 'id="settings-location"' in card
    assert "setActiveTab('solar')" in card and 'data-testid="location-solar-link"' in card
    solar = (PKG / "templates" / "tabs" / "solar.html").read_text()
    assert 'data-testid="solar-location-link"' in solar
    assert "sub: 'billing', card: 'settings-location'" in solar


def test_the_default_site_shows_its_location_and_links_to_it():
    assert 'data-testid="site-location"' in HTML
    j = HTML.index('data-testid="site-location"')
    row = HTML[HTML.rfind("<", 0, j):HTML.index("</", j) + 200]
    assert "s.is_default" in row and "settings-location" in row
