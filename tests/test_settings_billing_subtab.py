"""#674: Settings keeps a Billing & Utilities sub-tab with the sites, meters, retailers and
tariffs editors (owner 2026-11-16: "Restore the Billing Utilities sub tab"). #637 had
swapped it for a pointer to the Billing & Utilities page. Both show the one partial."""
import pathlib

PKG = pathlib.Path(__file__).resolve().parents[1] / "src" / "franklinwh_direct_connect_bridge"
HTML = (PKG / "templates" / "tabs" / "settings.html").read_text()
JS = (PKG / "static" / "js" / "settings_tab.js").read_text()


def test_the_sub_tab_is_back():
    assert "{ key: 'sites', label: 'Billing & Utilities' }" in JS
    assert JS.index("key: 'sites'") < JS.index("key: 'billing'")    # before Location & Prices


def test_it_holds_the_plans_and_meters_editors_not_a_pointer():
    i = HTML.index("x-show=\"sub==='sites'\"")
    block = HTML[i:HTML.index("x-show=\"sub==='billing'\"", i)]
    assert '{% include "partials/plans_meters.html" %}' in block
    assert 'data-testid="plans-moved"' not in HTML
