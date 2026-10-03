"""Phase 1: DB-backed gateway roster — CRUD, seed-from-env, and the /api/gateways
merge + live enable/disable (pollers stubbed so tests don't touch the network)."""
import os
import tempfile
import pytest
from fastapi.testclient import TestClient

from franklinwh_local_bridge import app as app_module
from franklinwh_local_bridge import db, supervisor, mockgw
from franklinwh_local_bridge import client as client_module


def _store(tmp):
    return db.MetricsStore(os.path.join(tmp, "m.db"))


def test_gateway_crud_and_seed(tmp_path):
    st = _store(str(tmp_path))
    assert st.gateways() == []
    # seed from env entries → first is default, idempotent
    assert st.seed_gateways([("10.0.0.1", "Home"), ("10.0.0.2", "Shed")]) == 2
    assert st.seed_gateways([("x", "y")]) == 0
    rows = st.gateways()
    assert [r["label"] for r in rows] == ["Home", "Shed"]
    assert rows[0]["is_default"] == 1 and rows[0]["port"] == 9000
    # create mock row
    st.create_gateway(gw_id="m1", label="Mock", is_mock=True, mock_units=3, publish_ha=False)
    m = st.gateway("m1")
    assert m["is_mock"] == 1 and m["mock_units"] == 3 and m["publish_ha"] == 0
    # update + delete
    assert st.update_gateway("m1", enabled=False)["enabled"] == 0
    assert st.delete_gateway("m1") is True and st.gateway("m1") is None


@pytest.fixture
def gw_client(tmp_path, monkeypatch):
    store = _store(str(tmp_path))
    monkeypatch.setattr(db, "get_store", lambda *a, **k: store)
    # Don't start real pollers in tests.
    async def _noop(*a, **k):
        return None
    monkeypatch.setattr(supervisor, "start_poller", _noop)
    monkeypatch.setattr(supervisor, "stop_poller", _noop)
    monkeypatch.setattr(supervisor, "is_running", lambda gid: False)
    # Don't bind real emulators for mock rows in tests.
    monkeypatch.setattr(mockgw, "start_mock", lambda gid, **k: "127.0.0.1:59999")
    monkeypatch.setattr(mockgw, "stop_mock", lambda gid: None)
    monkeypatch.setattr(client_module, "writes_enabled", lambda s: True)
    c = TestClient(app_module.create_app())
    return c, store


def test_api_roster_merge_and_toggle(gw_client):
    c, store = gw_client
    # add a real gateway
    r = c.post("/api/gateways", json={"label": "Home", "host": "10.0.0.1"})
    assert r.status_code == 201
    gid = r.json()["id"]
    row = r.json()
    assert row["enabled"] is True and row["model"] == "aGate" and row["is_mock"] is False
    # roster shows it (merged shape)
    roster = c.get("/api/gateways").json()
    assert any(g["id"] == gid and "enabled" in g and "model" in g for g in roster)
    # disable → enabled False, still listed
    assert c.patch(f"/api/gateways/{gid}", json={"enabled": False}).json()["enabled"] is False
    assert any(g["id"] == gid and g["enabled"] is False for g in c.get("/api/gateways").json())
    # mock create is accepted (in-process emulator; stubbed in tests)
    mr = c.post("/api/gateways", json={"label": "M", "is_mock": True, "mock_units": 3,
                                       "publish_ha": False})
    assert mr.status_code == 201 and mr.json()["is_mock"] is True
    assert mr.json()["model"] == "aGate (mock)"
    # delete
    assert c.delete(f"/api/gateways/{gid}").status_code == 200
    assert all(g["id"] != gid for g in c.get("/api/gateways").json())


def test_supervisor_start_stop_tracks_running():
    # Unit test the supervisor registry with a dummy coroutine instead of run_gateway.
    import asyncio
    from franklinwh_local_bridge.state import GatewayState

    async def scenario():
        gw = GatewayState(id="g1", label="G1")
        # monkeypatch run_gateway via the module ref used by start_poller
        import franklinwh_local_bridge.supervisor as sup

        async def fake_run(settings, gw, stop):
            await stop.wait()
        orig = sup.run_gateway
        sup.run_gateway = fake_run
        try:
            await sup.start_poller(None, gw)
            assert sup.is_running("g1") is True
            await sup.stop_poller("g1")
            await asyncio.sleep(0.05)
            assert sup.is_running("g1") is False
        finally:
            sup.run_gateway = orig
    asyncio.run(scenario())


def test_gateway_scan_endpoint(gw_client, monkeypatch):
    """Discover: /api/gateways/scan returns confirmed/unconfirmed candidates and marks
    already-added hosts. discover.scan is stubbed (no real network)."""
    c, store = gw_client
    from franklinwh_local import discover as _disc

    class _HR:
        def __init__(self, host, confirmed, sn):
            self.host = host; self.sendmqtt_open = True
            self.sendmqtt_confirmed = confirmed
            self.manifest = {"IBG_SN": sn} if sn else None

    store.create_gateway(gw_id="g1", label="Home", host="10.0.0.5")
    monkeypatch.setattr(_disc, "expand_targets", lambda spec: ["10.0.0.5", "10.0.0.9", "10.0.0.20"])
    monkeypatch.setattr(_disc, "scan", lambda targets, **k: [
        _HR("10.0.0.5", True, "SNHOME"), _HR("10.0.0.9", True, "SNNEW"),
        _HR("10.0.0.20", False, None)])
    r = c.post("/api/gateways/scan", json={"subnet": "10.0.0.0/24"})
    assert r.status_code == 200
    d = r.json()
    by = {x["host"]: x for x in d["candidates"]}
    assert by["10.0.0.5"]["confirmed"] and by["10.0.0.5"]["already_added"]      # existing
    assert by["10.0.0.9"]["confirmed"] and not by["10.0.0.9"]["already_added"]  # new aGate
    assert by["10.0.0.9"]["serial"] == "SNNEW"
    assert not by["10.0.0.20"]["confirmed"]                                     # port open only


def test_mock_emulator_read_through_split():
    """An in-process mock gateway is reachable via 127.0.0.1:<port> using the client's
    host:port split — summary + battery return synthetic data for N aPowers."""
    from franklinwh_local_bridge import mockgw, client, config
    host = mockgw.start_mock("itest", seed=7, units=3)
    assert host.startswith("127.0.0.1:")
    try:
        s = config.get_settings()
        summ = client.summary(s, host=host)
        assert summ["ok"] is True and summ.get("power", {}).get("soc") is not None
        bat = client.battery(s, host=host)
        assert bat["ok"] is True and bat["units"]["devNum"] == 3
        assert bat["cells"]["batSoc"] is not None
    finally:
        mockgw.stop_mock("itest")
        assert mockgw.is_running("itest") is False


def test_gateway_restart_endpoint(gw_client):
    c, store = gw_client
    r = c.post("/api/gateways", json={"label": "Home", "host": "10.0.0.1"})
    gid = r.json()["id"]
    assert c.post(f"/api/gateways/{gid}/restart").status_code == 200
    assert c.post("/api/gateways/nope/restart").status_code == 404


def test_edit_gateway_modal_wired():
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1] / "src/franklinwh_local_bridge"
    html = (root / "templates/tabs/settings.html").read_text()
    js = (root / "static/js/settings_tab.js").read_text()
    assert 'x-show="gwEdit.open"' in html and "openEditGateway(gw)" in html
    for m in ("openEditGateway(", "saveEditGateway(", "testEditGateway(",
              "restartEditGateway(", "removeEditGateway("):
        assert m in js, f"settings_tab.js missing {m}"
    # gwEdit is a permanent object (no null → no x-model teardown race)
    assert "gwEdit: { open: false" in js
