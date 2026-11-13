"""The period's summary under both charts (owner, 2026-11-12): more than four totals, the
same cards for Local and Cloud, and how much history each source holds ("1 year 23 days")."""
from pathlib import Path

from franklinwh_direct_connect_bridge import cloud_status

ROOT = Path(__file__).resolve().parents[1] / "src" / "franklinwh_direct_connect_bridge"
JS = (ROOT / "static" / "js" / "analytics_tab.js").read_text()
HTML = (ROOT / "templates" / "tabs" / "analytics.html").read_text()


def test_cloud_hands_its_payload_to_the_cards():
    assert "onData: (p) => { this.cloudData = p; }" in JS


def test_the_strip_shows_on_both_sources():
    strip = HTML[HTML.index("<!-- Stats strip -->"):]
    assert 'x-show="chartType !== \'flow\'"' in strip[:300]
    # and it isn't inside the Local-only block any more
    local = HTML.index("x-show=\"source === 'local' && chartType !== 'flow'\"")
    assert HTML.index("<!-- Stats strip -->") > HTML.index("</div><!-- /local -->", local)


def test_the_cards():
    for label in ("Battery discharged", "Battery charged", "Self-sufficiency", "Solar used on site",
                  "Battery cycles", "History"):
        assert f"'{label}'" in JS, label


def test_history_span_reads_in_years_and_days():
    assert "function analyticsSpan(" in JS
    # the wording, not a duration library
    assert "' year'" in JS and "' day'" in JS


def test_cloud_since_is_the_aGate_activation(monkeypatch):
    class Cloud:
        gateway = "G1"
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get_home_gateway_list(self):
            return {"result": [{"id": "G0", "activeTime": 1}, {"id": "G1", "activeTime": 1700000000000,
                                                                  "zoneInfo": "Australia/Sydney"}]}
    calls = []
    async def fake_client(email, pw, gw, source="status"):
        calls.append(gw); return Cloud()
    monkeypatch.setattr(cloud_status, "_client_for", fake_client)
    cloud_status._SINCE.clear()
    assert cloud_status.read_since("e", "p", "G1") == "2023-11-15"
    assert cloud_status.read_since("e", "p", "G1") == "2023-11-15"
    assert len(calls) == 1                     # it never changes: asked once


def test_cloud_since_endpoint_without_an_account(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from franklinwh_direct_connect_bridge import app as app_module, config, environment
    monkeypatch.setattr(environment, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "_settings", None)
    c = TestClient(app_module.create_app())
    gid = c.post("/api/gateways", json={"label": "Demo", "is_mock": True}).json().get("id")
    r = c.get("/api/analytics/cloud/since", params={"gateway": gid})
    assert r.status_code == 200 and "error" in r.json()


def test_the_package_has_on_data():
    assert "franklinwh-ha-cloud-analytics==0.1.27" in (ROOT.parents[1] / "pyproject.toml").read_text()


def test_cloud_since_is_the_sites_day():
    # a 'YYYY-MM-DD' read as the browser's midnight showed the day before east of the browser
    assert "this.fromSiteLocal(this.cloudSince + 'T00:00')" in JS
