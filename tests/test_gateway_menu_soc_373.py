"""Top bar gateway menu: each gateway's last-read SoC (#373).

The menu is built from /api/gateways, whose rows already carry ``soc`` and
``last_poll_ts`` from the poller's cache, so no new device reads. Each row shows the SoC
("55%"); when the reading is older than the poll interval allows, its age is added
("55% · 4 min ago")."""
import pathlib
import re
import time

import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import app as app_module
from franklinwh_direct_connect_bridge import config
from franklinwh_direct_connect_bridge import state as state_module

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src/franklinwh_direct_connect_bridge"


@pytest.fixture(autouse=True)
def _clean_registry():
    state_module.reset_gateways()
    yield
    state_module.reset_gateways()


def test_each_roster_row_carries_soc_its_read_time_and_the_poll_interval():
    gw = state_module.register_gateway("gw-home", "192.0.2.10", "Home")
    gw.last_summary = {"ok": True, "power": {"soc": 55}}
    gw.state_ts = time.time() - 240
    row = TestClient(app_module.create_app()).get("/api/gateways").json()[0]
    assert row["soc"] == 55
    assert row["last_poll_ts"] == pytest.approx(gw.state_ts)
    assert row["poll_interval"] == config.get_settings().poll_interval


def test_the_menu_row_shows_the_soc():
    html = (SRC / "templates/partials/topbar.html").read_text()
    menu = html[html.index('x-for="g in $store.app.gateways'):]
    menu = menu[:menu.index("</template>")]
    assert "$store.app.gwSocText(g)" in menu


def test_an_old_reading_shows_its_age():
    js = (SRC / "static/js/app.js").read_text()
    body = re.search(r"\n    gwSocText\(g\) \{(.*?)\n    \},", js, re.S).group(1)
    assert "g.soc" in body and "%" in body
    assert "g.poll_interval" in body and "g.last_poll_ts" in body
    assert "this.agoText(g.last_poll_ts)" in body
