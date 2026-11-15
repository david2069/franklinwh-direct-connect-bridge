"""#416 — Search for gateways on TCP 9000 by default, or on a port, list or range.

A real aGate always listens on 9000; any other port is an emulator (owner, 2026-10-31).
One result per address and port; "already added" is matched on both; the probe count
(hosts × ports) is capped; the Modbus TCP Server (aGate :502) is never probed."""
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_api import discover as _disc
from franklinwh_direct_connect_bridge import app as app_module
from franklinwh_direct_connect_bridge import db, supervisor, mockgw
from franklinwh_direct_connect_bridge import client as client_module

PKG = Path(__file__).resolve().parents[1] / "src" / "franklinwh_direct_connect_bridge"


@pytest.fixture
def gw_client(tmp_path, monkeypatch):
    store = db.MetricsStore(os.path.join(str(tmp_path), "m.db"))
    monkeypatch.setattr(db, "get_store", lambda *a, **k: store)

    async def _noop(*a, **k):
        return None
    monkeypatch.setattr(supervisor, "start_poller", _noop)
    monkeypatch.setattr(supervisor, "stop_poller", _noop)
    monkeypatch.setattr(supervisor, "is_running", lambda gid: False)
    monkeypatch.setattr(mockgw, "start_mock", lambda gid, **k: "127.0.0.1:59999")
    monkeypatch.setattr(mockgw, "stop_mock", lambda gid: None)
    monkeypatch.setattr(client_module, "writes_enabled", lambda s: True)
    return TestClient(app_module.create_app()), store


@pytest.fixture
def fake_scan(monkeypatch):
    """scan_ports stubbed: every pair is open; serials say what answered the login."""
    calls = []
    listeners = {("192.0.2.5", 9000): "SNREAL0001", ("192.0.2.5", 9020): "MOCK000020",
                 ("192.0.2.5", 9021): "MOCK000021", ("192.0.2.6", 9000): "MOCK000600",
                 ("192.0.2.7", 9000): None}

    def _scan(targets, ports, **k):
        targets, ports = list(targets), list(ports)
        calls.append((targets, ports))
        out = []
        for h in targets:
            for p in ports:
                if (h, p) in listeners:
                    sn = listeners[(h, p)]
                    out.append(_disc.PortResult(h, p, open=True, confirmed=sn is not None,
                                                manifest={"IBG_SN": sn} if sn else None))
        return out
    monkeypatch.setattr(_disc, "scan_ports", _scan)
    monkeypatch.setattr(_disc, "expand_targets",
                        lambda spec: ["192.0.2.5", "192.0.2.6", "192.0.2.7"])
    return calls


def test_blank_ports_searches_9000_only(gw_client, fake_scan):
    c, _ = gw_client
    d = c.post("/api/gateways/scan", json={"subnet": "192.0.2.0/24"}).json()
    assert fake_scan[-1][1] == [9000]
    assert d["ports"] == [9000]
    assert {(x["host"], x["port"]) for x in d["candidates"]} == {
        ("192.0.2.5", 9000), ("192.0.2.6", 9000), ("192.0.2.7", 9000)}


def test_list_and_range_give_one_result_per_address_and_port(gw_client, fake_scan):
    c, store = gw_client
    store.create_gateway(gw_id="g1", label="Emu 20", host="192.0.2.5", port=9020)
    r = c.post("/api/gateways/scan", json={"subnet": "192.0.2.0/24", "ports": "9000, 9020-9021"})
    assert r.status_code == 200
    assert fake_scan[-1][1] == [9000, 9020, 9021]
    by = {(x["host"], x["port"]): x for x in r.json()["candidates"]}
    assert by[("192.0.2.5", 9020)]["serial"] == "MOCK000020"
    assert by[("192.0.2.5", 9021)]["serial"] == "MOCK000021"
    # matched on address AND port: the 9020 one is added, the others on that IP are not
    assert by[("192.0.2.5", 9020)]["already_added"]
    assert not by[("192.0.2.5", 9000)]["already_added"]
    assert not by[("192.0.2.5", 9021)]["already_added"]


def test_a_host_given_as_address_and_port_counts_as_added(gw_client, fake_scan):
    c, store = gw_client
    store.create_gateway(gw_id="m", label="Mock", host="192.0.2.5:9021", port=9000)
    d = c.post("/api/gateways/scan", json={"subnet": "x", "ports": "9000,9021"}).json()
    by = {(x["host"], x["port"]): x for x in d["candidates"]}
    assert by[("192.0.2.5", 9021)]["already_added"]
    assert not by[("192.0.2.5", 9000)]["already_added"]


def test_other_ports_and_mock_serials_are_emulators(gw_client, fake_scan):
    c, _ = gw_client
    d = c.post("/api/gateways/scan", json={"subnet": "x", "ports": "9000,9020"}).json()
    by = {(x["host"], x["port"]): x for x in d["candidates"]}
    assert by[("192.0.2.5", 9000)]["emulator"] is False      # a real aGate
    assert by[("192.0.2.5", 9020)]["emulator"] is True       # not on 9000
    assert by[("192.0.2.6", 9000)]["emulator"] is True       # serial starts MOCK


def test_modbus_502_is_never_probed(gw_client, fake_scan):
    c, _ = gw_client
    assert c.post("/api/gateways/scan", json={"subnet": "x", "ports": "500-503"}).status_code == 200
    assert fake_scan[-1][1] == [500, 501, 503]
    r = c.post("/api/gateways/scan", json={"subnet": "x", "ports": "502"})
    assert r.status_code == 400 and "502" in r.json()["detail"]


def test_bad_port_spec_is_400(gw_client, fake_scan):
    c, _ = gw_client
    for spec in ("abc", "70000", "9030-9020"):
        r = c.post("/api/gateways/scan", json={"subnet": "x", "ports": spec})
        assert r.status_code == 400, spec
    assert fake_scan == []


def test_probe_count_is_capped(gw_client, fake_scan, monkeypatch):
    c, _ = gw_client
    monkeypatch.setattr(_disc, "expand_targets",
                        lambda spec: [f"192.0.2.{i}" for i in range(1, 255)])
    r = c.post("/api/gateways/scan", json={"subnet": "192.0.2.0/24", "ports": "9020-9030"})
    assert r.status_code == 400
    assert "narrow" in r.json()["detail"] and "2794" in r.json()["detail"]
    assert fake_scan == []


def test_roster_labels_a_gateway_on_another_port_as_emulator(gw_client):
    c, store = gw_client
    store.create_gateway(gw_id="real", label="Home", host="192.0.2.5", port=9000)
    store.create_gateway(gw_id="emu", label="Emu", host="192.0.2.5", port=9020)
    by = {g["id"]: g for g in c.get("/api/gateways").json()}
    assert by["real"]["emulator"] is False and by["emu"]["emulator"] is True


def test_ui_sends_ports_and_adds_each_result_on_its_port():
    js = (PKG / "static/js/settings_tab.js").read_text()
    add = js[js.index("async addFromScan(c)"):js.index("// ── Mock gateway")]
    assert "port: c.port" in add
    assert "scanPorts" in js[js.index("async discoverGateways()"):js.index("confirmedCands()")]
    wiz = (PKG / "static/js/setup_wizard.js").read_text()
    assert "port: c.port" in wiz[wiz.index("async addFound(c)"):wiz.index("async addManual()")]
    assert "scan_ports" in wiz[wiz.index("async scan()"):wiz.index("async addFound(c)")]
    settings = (PKG / "templates/tabs/settings.html").read_text()
    wizard = (PKG / "templates/partials/setup_wizard.html").read_text()
    assert 'x-model="scanPorts"' in settings and 'x-model="scan_ports"' in wizard
    assert "Emulator" in settings and "Emulator" in wizard
