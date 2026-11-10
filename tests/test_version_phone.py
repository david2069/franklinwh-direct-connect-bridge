"""#326: on a phone the sidebar (and its version line) is hidden, so the More sheet shows
the version and build too."""
import pathlib

NAV = (pathlib.Path(__file__).resolve().parents[1]
       / "src/franklinwh_direct_connect_bridge/templates/partials/bottom-nav.html").read_text()


def test_more_sheet_shows_version_and_build():
    assert "$store.app.version" in NAV and "$store.app.buildAsset" in NAV
