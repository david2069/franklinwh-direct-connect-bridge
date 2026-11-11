"""The setup wizard as a guide over what already exists (owner, 2026-11-11): after the
first run it opens on a list of everything worth setting up, each with Done / To do. Simple
ones are answered in the wizard; the rest open the Settings card that already does them."""
import re
from pathlib import Path

from franklinwh_direct_connect_bridge import setup_wizard

ROOT = Path(__file__).resolve().parents[1] / "src/franklinwh_direct_connect_bridge"

FACTS = dict(cloud=False, mqtt=False, home_assistant=False, billing=False,
             default_mode=False, automation=False, notifications=False, security=False,
             accounts=False)


def test_the_list_and_its_order():
    t = setup_wizard.tasks(**FACTS)
    ess = [x["id"] for x in t if x["group"] == "essential"]
    adv = [x["id"] for x in t if x["group"] == "advanced"]
    assert ess == ["cloud", "mqtt", "home_assistant", "billing", "default_mode", "automation"]
    assert adv == ["notifications", "security", "accounts", "system_view"]
    for x in t:
        assert x["title"] and x["detail"]
        assert bool(x.get("inline")) != bool(x.get("open")), x["id"]   # one way in, not two
    assert {x["id"]: x["inline"] for x in t if x.get("inline")} == {
        "cloud": "cloud", "mqtt": "publish", "default_mode": "mode"}


def test_done_follows_the_facts():
    t = {x["id"]: x for x in setup_wizard.tasks(**{**FACTS, "billing": True, "security": True})}
    assert t["billing"]["satisfied"] is True and t["security"]["satisfied"] is True
    assert t["cloud"]["satisfied"] is False
    assert t["system_view"]["satisfied"] is None        # nothing to be "done": no chip


def test_every_open_lands_on_a_card_that_exists():
    html = (ROOT / "templates/tabs/settings.html").read_text()
    subs = set(re.findall(r"sub==='(\w+)'", html))
    for x in setup_wizard.tasks(**FACTS):
        o = x.get("open") or {}
        if o.get("card"):
            assert o["sub"] in subs, x["id"]
            assert f'id="{o["card"]}"' in html, (x["id"], o["card"])


def test_api_setup_carries_the_tasks(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from franklinwh_direct_connect_bridge import app as app_module, config, environment, db
    from franklinwh_direct_connect_bridge.db import MetricsStore
    st = MetricsStore(str(tmp_path / "m.db"))
    monkeypatch.setattr(environment, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "_settings", None)
    monkeypatch.setattr(db, "get_store", lambda s: st)
    c = TestClient(app_module.create_app())
    d = c.get("/api/setup").json()
    ids = [x["id"] for x in d["tasks"]]
    assert ids[0] == "cloud" and "system_view" in ids
    mode = next(x for x in d["tasks"] if x["id"] == "default_mode")
    assert mode["satisfied"] is False
    c.put("/api/constants", json={"default_operating_mode": "tou"})
    mode = next(x for x in c.get("/api/setup").json()["tasks"] if x["id"] == "default_mode")
    assert mode["satisfied"] is True


def test_the_wizard_has_the_hub():
    js = (ROOT / "static/js/setup_wizard.js").read_text()
    html = (ROOT / "templates/partials/setup_wizard.html").read_text()
    assert "step === 'hub'" in html and "step === 'mode'" in html
    assert "openTask(" in js and "fwh-open-settings" in js
    # Finishing the first run lands on the list; reopening a set-up bridge goes straight there.
    assert "this.toHub()" in js
    # Closing the list must not turn a finished setup into "skipped".
    assert re.search(r"async close\(\)\s*\{[^}]*hub", js)
