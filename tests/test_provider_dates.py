"""Retailer dates save, blank date boxes stay blank, and Explain points to where the
tariff goes (owner, 2026-11-14 screenshots)."""

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import app as app_module, config, db, environment
from franklinwh_direct_connect_bridge.db import MetricsStore

ROOT = Path(__file__).resolve().parents[1] / "src" / "franklinwh_direct_connect_bridge"


def _save_utility_body() -> str:
    js = (ROOT / "static/js/settings_tab.js").read_text()
    fn = js[js.index("async saveUtility()"):js.index("async deleteUtility(")]
    return fn[fn.index("const body"):fn.index("try {")]


def test_save_sends_the_provider_dates_and_the_export_note():
    body = _save_utility_body()
    for k in ("effective_start", "effective_end", "export_note"):
        assert k in body, f"Save drops {k}"


def test_a_cleared_provider_date_is_cleared(tmp_path):
    s = MetricsStore(str(tmp_path / "m.db"))
    s.create_utility(uid="u1", name="AGL", effective_start="2026-01-01",
                     effective_end="2026-11-01")
    s.update_utility("u1", effective_start="2026-02-01", effective_end="")
    u = s.utility("u1")
    assert u["effective_start"] == "2026-02-01"
    assert u["effective_end"] is None                  # blank = current
    s.close()


def test_every_date_box_is_blank_when_empty():
    """Safari draws today's date, greyed, in an empty date box: a date nobody set."""
    for tab in ("settings.html", "scheduler.html"):
        html = (ROOT / "templates/tabs" / tab).read_text()
        for tag in re.findall(r"<input[^>]*type=\"date\"[^>]*>", html, re.S):
            assert "date-empty" in tag, f"{tab}: {tag[:80]}"
    css = (ROOT / "static/css/design-system.css").read_text()
    assert ".date-empty:not(:focus)::-webkit-datetime-edit" in css


def test_explain_says_where_the_tariff_goes():
    app = (ROOT / "app.py").read_text()
    assert "Settings → Billing" not in app
    assert "Settings → Sites & Billing → your meter" in app


@pytest.fixture
def api(tmp_path, monkeypatch):
    store = MetricsStore(str(tmp_path / "m.db"))
    monkeypatch.setattr(environment, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "_settings", None)
    monkeypatch.setattr(db, "get_store", lambda s: store)
    yield TestClient(app_module.create_app())
    store.close()
    config._settings = None


def test_a_retailer_saves_with_no_start_date(api):
    """Owner: Save works with no start date — blank dates are no dates."""
    r = api.post("/api/utilities", json={"name": "AGL", "effective_start": "",
                                         "effective_end": ""})
    assert r.status_code == 201, r.text
    uid = r.json()["id"]
    assert r.json()["effective_start"] is None and r.json()["effective_end"] is None
    r = api.patch(f"/api/utilities/{uid}", json={"name": "AGL Energy", "effective_start": "",
                                               "effective_end": "", "export_note": ""})
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "AGL Energy" and r.json()["effective_start"] is None
