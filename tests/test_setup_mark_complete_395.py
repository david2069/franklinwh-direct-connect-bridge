"""Settings → Setup: Mark complete shows its result on the card (#395).

``setSetupState`` never checked the response, so a 401, 422 or 5xx looked the same as
success, and success showed nothing either: the card never showed the stored state and the
button stayed. Now the result (or the error with its HTTP status) shows on the Setup card
and stays there, the card shows the stored state, and once complete the button becomes
**Mark not complete**."""
import pathlib
import re

from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import app as app_module

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src/franklinwh_direct_connect_bridge"


def _fn(js: str, name: str) -> str:
    m = re.search(r"async " + name + r"\(value\) \{(.*?)\n    \},", js, re.S)
    assert m, f"{name} not found"
    return m.group(1)


def _setup_card() -> str:
    html = (SRC / "templates/tabs/settings.html").read_text()
    start = html.index("<!-- ══ Setup ══")
    return html[start:html.index('<template x-for="st in ($store.app.setup.steps', start)]


def test_a_failed_post_is_reported_not_swallowed():
    body = _fn((SRC / "static/js/app.js").read_text(), "setSetupState")
    assert "r.ok" in body                           # the response is checked
    assert "HTTP ${r.status}" in body               # the error carries its status
    assert "setupStateMsg" in body                  # and lands on the card


def test_the_setup_card_shows_the_result_and_the_stored_state():
    card = _setup_card()
    assert "$store.app.setupStateMsg" in card       # result shown inside the card
    assert "$store.app.setup.state" in card         # Complete / Skipped / Not done
    for word in ("Complete", "Skipped", "Not done"):
        assert word in card
    assert "toast" not in card


def test_complete_swaps_the_button_for_mark_not_complete():
    card = _setup_card()
    assert "setSetupState('pending')" in card and "Mark not complete" in card
    mark = next(l for l in card.splitlines() if "x-show" in l and "required_satisfied" in l)
    assert "state !== 'done'" in mark


def test_the_stored_state_round_trips_through_the_api():
    c = TestClient(app_module.create_app())
    assert c.post("/api/setup/state", json={"state": "done"}).json() == {"state": "done"}
    assert c.get("/api/setup").json()["state"] == "done"
    assert c.post("/api/setup/state", json={"state": "pending"}).json() == {"state": "pending"}
    assert c.post("/api/setup/state", json={"state": "nope"}).status_code == 422
