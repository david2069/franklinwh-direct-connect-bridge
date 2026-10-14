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


# --- end-user build: no sibling checkouts, no dev-cycle coupling ---------------------------

def test_wheels_directory_is_committed():
    """The Dockerfile COPYs wheels/, so a clean clone must contain it or the build fails.

    This is what broke the end-user and Home Assistant add-on path: wheels/ existed only on
    a developer's machine, created by tools/build_image.sh.
    """
    import subprocess
    root = TABS.parents[2]
    tracked = subprocess.run(["git", "ls-files", "wheels"], cwd=root,
                             capture_output=True, text=True).stdout.split()
    assert "wheels/.gitkeep" in tracked, "wheels/.gitkeep is not committed; a clean clone cannot build"


def test_dockerfile_installs_declared_dependencies():
    """One dependency list — pyproject.toml — not a second copy in the Dockerfile.

    It used to repeat the list and install with --no-deps, so the two could drift and an
    end-user build could silently differ from a developer's.
    """
    lines = (TABS.parents[2] / "Dockerfile").read_text().splitlines()
    # Executable lines only: a comment EXPLAINING --no-deps must not fail this test, which
    # is exactly what a naive substring check did on first run.
    code = "\n".join(ln for ln in lines if not ln.lstrip().startswith("#"))
    assert '-e ".[cloud]"' in code
    assert "--no-deps" not in code, "Dockerfile is bypassing the declared dependencies again"


def test_build_script_keeps_the_wheels_directory():
    """`rm -rf wheels` would delete the committed .gitkeep. Clear the wheels, keep the dir."""
    script = (TABS.parents[2] / "tools/build_image.sh").read_text()
    assert 'rm -rf "$HERE/wheels"' not in script
    assert 'rm -f "$HERE/wheels"/*.whl' in script
