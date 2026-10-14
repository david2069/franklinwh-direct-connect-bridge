"""Two UI defects that were fixed but never pinned, so nothing stopped them returning.

Both are template-shape tests. They assert the STRUCTURE the fix depends on, not the
styling: a breakpoint class creeping back onto the nav, or the mock gateway form drifting
back above the real one, is exactly how each defect originally arrived.
"""
from pathlib import Path

TABS = Path(__file__).resolve().parents[1] / "src/franklinwh_direct_connect_bridge/templates"


def _read(rel: str) -> str:
    return (TABS / rel).read_text()


# --- DEF-BOTTOM-NAV-ALWAYS-ON -------------------------------------------------------------

def test_nav_visibility_is_measured_not_breakpoint_classed():
    """The sidebar and bottom nav must switch on the measured `narrow` store.

    The original defect: visibility rode on Tailwind's `lg:hidden` / `hidden lg:flex`,
    which the runtime CDN did not reliably generate inside Jinja includes, so the
    breakpoint never fired and the bottom nav stayed on at desktop widths.
    """
    sidebar, bottom = _read("partials/sidebar.html"), _read("partials/bottom-nav.html")

    assert 'x-show="!$store.app.narrow"' in sidebar
    assert 'x-show="$store.app.narrow"' in bottom

    for name, html in (("sidebar.html", sidebar), ("bottom-nav.html", bottom)):
        for cls in ("lg:hidden", "hidden lg:flex", "md:hidden", "hidden md:flex"):
            assert cls not in html, (
                f"{name} is back on a Tailwind breakpoint class ({cls!r}); "
                "visibility must come from $store.app.narrow — see DEF-BOTTOM-NAV-ALWAYS-ON"
            )


def test_more_sheet_is_gated_on_narrow():
    """The More sheet belongs to the bottom nav, so it must not open on a wide window."""
    assert 'x-show="$store.app.moreOpen && $store.app.narrow"' in _read("partials/bottom-nav.html")


# --- DEF-ADDGW-DEFAULT-REAL ---------------------------------------------------------------

def test_real_gateway_is_offered_before_the_mock():
    """A real gateway is the normal thing to add; a mock is the testing edge case.

    The defect was the emphasis: the mock form was primary and expanded while the real
    one sat behind an "advanced" collapse.
    """
    html = _read("tabs/settings.html")
    real = html.index("Add a gateway manually")
    mock = html.index("Add a mock gateway (testing)")
    assert real < mock, "the mock gateway form is offered before the real one again"


def test_mock_gateway_form_is_collapsed_by_default():
    html = _read("tabs/settings.html")
    start = html.index("Add a mock gateway (testing)")
    details = html.rindex("<details", 0, start)
    opening = html[details:start]
    assert " open" not in opening, "the mock gateway disclosure is expanded by default again"
