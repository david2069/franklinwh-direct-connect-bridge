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


def test_yes_never_patches_a_mock_the_wizard_created():
    """A mock is never published (#711); the server answers its publish_ha PATCH with 422,
    which the first-run Yes sent for the mocks it had just created (a console error)."""
    js = (PKG / "static/js/setup_wizard.js").read_text()
    create = js[js.index("async createMock()"):js.index("// Sign in for real")]
    assert "createdIds.push" not in create          # mocks are not the gateways Yes opts in
    body = js[js.index("async publishYes()"):js.index("publishNo()")]
    assert "!g.is_mock" in body                     # the setup-list path skips them too
