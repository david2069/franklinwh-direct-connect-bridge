"""Owner 2026-11-25: remove the Allow writes switch from Settings → Automation → Control.
It has done nothing since 0.5.2 (client.writes_enabled() is always True). The option is
still accepted (add-on options, PUT /api/settings) so older setups keep working."""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src/franklinwh_direct_connect_bridge"


def test_settings_has_no_allow_writes_switch():
    html = (SRC / "templates/tabs/settings.html").read_text()
    assert "Allow writes" not in html
    assert "saveOne({allow_writes" not in html
    js = (SRC / "static/js/settings_tab.js").read_text()
    assert "form.allow_writes" not in js
    assert "allow_writes: false, log_level" not in js


def test_guide_no_longer_describes_the_switch():
    for name in ("control.md", "generator.md"):
        src = (ROOT / "docs/guide" / name).read_text()
        assert "**Allow writes**" not in src
        assert "02-allow-writes.png" not in src
