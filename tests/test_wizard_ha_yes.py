"""#264: the wizard's Yes opts its gateways in even when the broker is already on."""

from pathlib import Path

from franklinwh_direct_connect_bridge import app as app_module

PKG = Path(app_module.__file__).parent


def test_yes_is_not_disabled_by_publishing():
    html = (PKG / "templates/partials/setup_wizard.html").read_text()
    assert ':disabled="ha.busy || ha.publishing"' not in html
    assert ':disabled="ha.busy"\n                        @click="publishYes()">Yes' in html


def test_yes_patches_the_wizard_gateways_when_the_broker_is_already_on():
    js = (PKG / "static/js/setup_wizard.js").read_text()
    body = js[js.index("async publishYes()"):js.index("publishNo()")]
    assert "this.ha.publishing ?" in body          # skips re-enabling the broker
    assert "publish_ha: true" in body              # but still opts each gateway in
