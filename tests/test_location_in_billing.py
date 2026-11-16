"""Location & Solar sits under Settings → Location & Prices (owner, 2026-11-13, #582
follow-up; the sub-tab was Sites & Billing until sites, meters and tariffs moved to the
Billing & Utilities page, #613; restored as Billing & Utilities, #674). The default site's card there links to it."""
import pathlib

from franklinwh_direct_connect_bridge import scheduler

PKG = pathlib.Path(__file__).resolve().parents[1] / "src" / "franklinwh_direct_connect_bridge"
HTML = (PKG / "templates" / "tabs" / "settings.html").read_text()
PLANS = (PKG / "templates" / "partials" / "plans_meters.html").read_text()


def _sub_of(i):
    """The settings sub-tab whose block holds position ``i``."""
    j = HTML.rfind("x-show=\"sub==='", 0, i)
    return HTML[j + len("x-show=\"sub==='"):HTML.index("'", j + len("x-show=\"sub==='"))]


def test_location_and_solar_is_under_location_and_prices():
    i = HTML.index("<!-- ══ Location & Solar ══ -->")
    assert _sub_of(i) == "billing"
    prices = HTML.index("<!-- ══ Prices (#582)")
    assert i < prices


def test_messages_point_to_the_new_place():
    assert "Location & Prices → Location & Solar" in scheduler._SETUP_SOLAR
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
    assert 'data-testid="site-location"' in PLANS
    j = PLANS.index('data-testid="site-location"')
    row = PLANS[PLANS.rfind("<", 0, j):PLANS.index("</", j) + 200]
    assert "s.is_default" in row and "settings-location" in row
