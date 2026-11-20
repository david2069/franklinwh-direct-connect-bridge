"""Custom roles (standalone): the map of which API reads each tab needs stays in step with
the UI and with the routes, so a role given a tab can use it and nothing is unclassified."""
import re
from pathlib import Path

import pytest

from franklinwh_direct_connect_bridge import tab_access

PKG = Path(__file__).resolve().parents[1] / "src" / "franklinwh_direct_connect_bridge"
APP = (PKG / "app.py").read_text()
GET_ROUTES = sorted({re.sub(r"\{[^}]+\}", "{}", p)
                     for p in re.findall(r'@app\.get\("(/api/[^"]*)"', APP)})

#: UI file → the tabs whose role must be able to use it. app.js carries the dashboard,
#: the top bar and the Control tab's code; alerts.js is on every page.
FILES = {
    "static/js/app.js": ("dashboard", "control"),
    "static/js/alerts.js": (),
    "static/js/energy_flow_card.js": ("dashboard",),
    "static/js/solar_forecast_card.js": ("dashboard",),
    "static/js/battery_control.js": ("control",),
    "static/js/install_profile.js": ("settings",),
    "static/js/setup_wizard.js": ("settings",),
    "static/js/integrations_tab.js": ("settings",),
    "static/js/terminal.js": ("device",),
    "static/js/troubleshoot.js": ("health",),
    "templates/index.html": ("systemview",),
}
for _f in (PKG / "static" / "js").glob("*_tab.js"):
    FILES.setdefault(f"static/js/{_f.name}", (_f.name[:-len("_tab.js")],))
for _f in (PKG / "templates" / "tabs").glob("*.html"):
    FILES.setdefault(f"templates/tabs/{_f.name}", (_f.stem,))


def _is_get(path: str) -> bool:
    """A UI path that reaches a GET route (the UI's POSTs are writes, not reads)."""
    p = path.rstrip("/")
    return any(r == p or r.startswith(p + "/") or
               re.fullmatch(re.escape(r).replace(r"\{\}", "[^/]+"), p) for r in GET_ROUTES)


def _ui_paths(rel: str) -> set[str]:
    text = (PKG / rel).read_text()
    return {"/" + m for m in re.findall(r"""['"`/](api/[A-Za-z0-9_/-]+)""", text)
            if not m.startswith("api/hassio")}


def test_the_tabs_are_the_ui_tabs():
    for tab in tab_access.TABS:
        if tab != "systemview":
            assert (PKG / "templates" / "tabs" / f"{tab}.html").exists(), tab


@pytest.mark.parametrize("rel,tabs", sorted(FILES.items()))
def test_each_tab_can_read_what_its_page_calls(rel, tabs):
    missing = [p for p in _ui_paths(rel) if _is_get(p) and not tab_access.read_allowed(tabs, p)
               and not tab_access._under(p, tab_access.ADMIN_ONLY_READS)]
    assert missing == [], f"{rel} ({', '.join(tabs) or 'shared'}) calls {missing}"


def test_every_read_route_is_classified():
    every = tuple(p for ps in tab_access.TAB_READS.values() for p in ps)
    loose = [r for r in GET_ROUTES
             if not tab_access._under(r, tab_access.SHARED_READS + tab_access.ADMIN_ONLY_READS + every)]
    assert loose == []


def test_dashboard_and_system_view_only():
    tabs = ("dashboard", "systemview")
    assert tab_access.read_allowed(tabs, "/api/gateways/gw1/summary")
    assert tab_access.read_allowed(tabs, "/api/system")
    assert tab_access.read_allowed(tabs, "/api/metrics")
    for p in ("/api/billing/bills", "/api/logs", "/api/schedules", "/api/network",
              "/api/settings", "/api/ha/instances", "/api/admin/backups"):
        assert not tab_access.read_allowed(tabs, p), p


def test_admin_only_reads_stay_admin_only():
    every = tuple(tab_access.TABS)
    for p in tab_access.ADMIN_ONLY_READS:
        assert not tab_access.read_allowed(every, p)
