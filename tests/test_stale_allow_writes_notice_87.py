"""#87: the Control and Circuits tabs had a "writes are disabled" card telling the user to
set ALLOW_WRITES=true. That setting no longer blocks anything (client.writes_enabled()
always returns True), so the card's advice is wrong and it can only flash before the
summary loads. Neither tab carries it now."""
import pathlib

import pytest

TPL = pathlib.Path(__file__).resolve().parents[1] / "src/franklinwh_direct_connect_bridge/templates/tabs"


@pytest.mark.parametrize("name", ["control.html", "circuits.html"])
def test_no_set_allow_writes_notice(name):
    src = (TPL / name).read_text()
    assert "ALLOW_WRITES=true</span>" not in src
    assert "writes are disabled (read-only)" not in src
