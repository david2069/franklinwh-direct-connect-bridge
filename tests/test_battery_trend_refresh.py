"""#317: the Battery tab's charts must refresh in place on every poll.

Measured on the HAOS VM, 2026-10-24: samples and chart labels grew every 2 s, but the
canvas never changed. Each in-place `update('none')` on a Chart reached through Alpine's
reactive proxy threw "Maximum call stack size exceeded", swallowed by draw()'s catch.
Only a recreate (switching metric and back) drew, once.
"""
import pathlib
import re

JS = (pathlib.Path(__file__).resolve().parents[1]
      / "src/franklinwh_direct_connect_bridge/static/js/battery_tab.js").read_text()


def _in_place_updates() -> list[str]:
    """Every receiver that `.update('none')` is called on."""
    return re.findall(r"(\w+(?:\.\w+)*)\.update\('none'\)", JS)


def test_in_place_chart_updates_never_go_through_the_reactive_proxy():
    calls = _in_place_updates()
    assert len(calls) >= 3, calls                       # trend, per-unit stack, live
    for recv in calls:
        assert not recv.startswith("this."), (
            f"{recv}.update('none') runs through Alpine's proxy and recurses (#317); "
            "take Alpine.raw(...) first")
    for name in ("this._chart", "this._liveChart", "this._stackCharts[u]"):
        assert f"Alpine.raw({name})" in JS, f"{name} is updated without Alpine.raw"


def test_header_time_uses_the_site_zone_like_the_chart():
    assert "this.lastAt = new Date().toLocaleTimeString()" not in JS
    assert "this.lastAt = this.$store.app._fmtSiteTime(" in JS
