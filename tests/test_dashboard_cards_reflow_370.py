"""#370: Dashboard cards cut text off or let it run past the edge.

Seen by the owner at 0.5.17 with the sidebar open, and measured on 0.5.49 at 1024–1180 px
wide: the three-column row starts at a 1024 px window, but the sidebar takes ~210 px, so
the Battery State of Charge card was left ~240 px. Its model, Mode ("Self-…") and Battery
("Cha…") were cut off and Run status ran past the card's edge; the Energy card's second
column ("Discharged 3.74") sat on its right edge.

The fix makes the cards reflow from their own width rather than the window's: the SoC
values drop under the ring when the card is narrow and wrap instead of truncating, and
the Energy figures go to one column when two don't fit. These are template-shape tests;
the Playwright measurements are in the PR.
"""
import re
from pathlib import Path

DASH = (Path(__file__).resolve().parents[1]
        / "src/franklinwh_direct_connect_bridge/templates/tabs/dashboard.html").read_text()


def _block(testid: str) -> str:
    """The element with ``data-testid=testid``, up to the next card."""
    i = DASH.index(f'data-testid="{testid}"')
    start = DASH.rindex("<", 0, i)
    end = DASH.find("<!--", i)
    return DASH[start:end if end > 0 else None]


def test_soc_card_values_drop_under_the_ring_when_narrow():
    body = _block("dash-soc-body")
    tag = body[:body.index(">")]
    assert "flex-wrap" in tag, "the ring and its values must wrap, not squeeze"
    vals = _block("dash-soc-values")
    vtag = vals[:vals.index(">")]
    assert re.search(r"min-width:\s*\d+(\.\d+)?rem", vtag), \
        "the values need a minimum width, so they move under the ring instead of truncating"


def test_soc_card_text_wraps_instead_of_being_cut_off():
    card = DASH[DASH.index("<!-- Battery State of Charge -->"):DASH.index("<!-- Power flow")]
    assert "truncate" not in card, "a cut-off value hides the mode or charge state (#370)"
    header = card[card.index('<div class="flex'):]
    assert "flex-wrap" in header[:header.index(">")], "the model wraps under the title"


def test_energy_figures_go_to_one_column_when_two_do_not_fit():
    grid = _block("dash-energy-grid")
    tag = grid[:grid.index(">")]
    assert "grid-cols-2" not in tag
    assert re.search(r"grid-template-columns:\s*repeat\(auto-fit,\s*minmax\(", tag)


def test_every_soc_and_energy_value_is_still_there():
    """Owner rule: nothing removed or renamed."""
    for label in ("Battery State of Charge", "Reserved", "Mode", "Battery", "Run status"):
        assert label in DASH, label
    for label in ("Solar", "Home", "Charged", "Discharged", "Grid in", "Grid out"):
        assert re.search(rf'text-slate-500">{label}\b', DASH), label
