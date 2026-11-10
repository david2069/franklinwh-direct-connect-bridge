"""#368: with the generator feature off, the Operating windows Edit buttons are disabled
(correct) but the card wasn't dimmed like Start / stop and Maintenance run, and the reason
was only in a tooltip. Owner, 2026-10-28: the card says on screen to install and configure
the generator module; editing stays unavailable until then."""
import pathlib

TAB = (pathlib.Path(__file__).resolve().parents[1]
       / "src/franklinwh_direct_connect_bridge/templates/tabs/generator.html").read_text()


def _windows_card():
    i = TAB.index("<!-- charge windows")
    return TAB[i:TAB.index("<!-- config editors", i)]


def test_windows_card_dims_while_feature_off():
    card = _windows_card()
    assert """<div class="card overflow-hidden" :class="data.enabled ? '' : 'opacity-60'">""" in card


def test_windows_card_says_why_on_screen():
    card = _windows_card()
    i = card.index('x-show="!data.enabled"')
    reason = card[i:card.index("</p>", i)]
    assert "install and configure the generator module" in reason.lower()
