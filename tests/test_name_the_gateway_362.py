"""#362 — a control that reads one gateway names it. Automation's **Derive from aPower**
fills an install-wide constant from the aPower count of the gateway on screen, and Billing &
Utilities' **Sync from gateway** reads one gateway of the site; neither said which."""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1] / "src/franklinwh_direct_connect_bridge"
SETTINGS = (ROOT / "templates/tabs/settings.html").read_text()
JS = (ROOT / "static/js/settings_tab.js").read_text()


def test_derive_from_apower_names_the_gateway_it_read():
    assert 'data-testid="apower-read-from"' in SETTINGS
    assert "selectedGatewayLabel" in SETTINGS.split('data-testid="apower-read-from"')[1][:400]


def test_sync_from_gateway_names_the_gateway():
    assert 'data-testid="location-sync-gateway"' in SETTINGS
    assert "locSyncGatewayLabel" in JS
    # the result names it too
    assert "'Location synced from ' + " in JS
