"""A roster change must refresh the dashboard, not just change a variable.

Reported 2026-10-15 from the live Home Assistant add-on, with no gateway configured: the
dashboard sat on its empty state (Offline / Unknown / "--") and never came to life, while
picking the same gateway from the switcher worked immediately.

That difference IS the defect. `selectGateway()` refetches — poll, generator, history —
and `loadGateways()` only assigned `this.selectedGateway`. So when the first gateway
appeared (fresh install, or one added by the wizard) the id changed silently and nothing
asked the server for anything.

Text assertions on the controller: there is no Python behind this view, and the
alternative is no coverage of a defect that has now been reported twice.
"""
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "src/franklinwh_direct_connect_bridge/static/js/app.js"


def _fn(name: str) -> str:
    """One function body out of the Alpine store, by its opening line."""
    js = APP.read_text()
    start = js.index(name)
    end = js.index("\n    },", start)
    return js[start:end]


def _load_gateways() -> str:
    return _fn("async loadGateways()")


def test_a_changed_selection_goes_through_selectgateway():
    body = _load_gateways()
    assert "this.selectGateway(next)" in body, (
        "assigning selectedGateway refetches nothing — the dashboard stays empty"
    )
    assert "next !== prev" in body            # only when it actually changed


def test_the_first_paint_does_not_double_poll():
    """init() already polls; the auto-select must not fire a second one at boot."""
    body = _load_gateways()
    assert "this._booted" in body
    js = APP.read_text()
    assert "this._booted = true;" in js


def test_the_roster_is_polled_fast_while_there_is_no_gateway():
    """With no gateway the roster IS the screen; 120s of staleness is the whole UI."""
    body = _fn("_tuneGatewayPoll() {")
    assert "10000" in body and "120000" in body
    assert "this.gateways.length ? 120000 : 10000" in body
    assert "clearInterval(this._gwInterval)" in body      # no interval left running


def test_selecting_refetches_and_is_not_remembered():
    """The manual path must keep doing what made it the one that worked. The choice is not
    remembered across reloads: the page opens on the default gateway (#383)."""
    body = _fn("selectGateway(id)")
    for call in ("this.poll()", "this._loadGeneratorInstalled()", "this.loadHistory("):
        assert call in body
    assert "localStorage" not in body


# --- the add-on cannot discover from its own network -----------------------------------------
# Live add-on, 2026-10-15: Discover offered 172.30.33.0/24 — the Supervisor's internal docker
# network — and found nothing, on a site whose aGate answered fine on the LAN.

def test_internal_docker_ranges_are_never_offered_as_a_scan_subnet():
    from franklinwh_direct_connect_bridge.ha_supervisor import _slash24
    for internal in ("172.30.33.4/24", "172.17.0.2/16", "127.0.0.1/8"):
        assert _slash24(internal) is None
    assert _slash24("192.168.0.17/24") == "192.168.0.0/24"
    assert _slash24("not-an-address") is None


def test_host_subnets_are_empty_outside_the_addon(monkeypatch):
    """No Supervisor, no guess — the caller falls through to its other sources."""
    from franklinwh_direct_connect_bridge import ha_supervisor
    monkeypatch.setattr(ha_supervisor, "IS_HA_ADDON", False)
    assert ha_supervisor.host_lan_subnets() == []
