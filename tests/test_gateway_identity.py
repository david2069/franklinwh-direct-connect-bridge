"""#381 — a gateway's id is the bridge's own and its aGate serial is locked to it 1:1:
locked on first report, a duplicate is refused, a changed serial stops the gateway."""
import asyncio
import sqlite3

from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import app as app_module, config, db, poller, state
from franklinwh_direct_connect_bridge.state import GatewayState


def _store():
    return db.get_store(config.get_settings())


def test_serial_locks_on_first_report_and_never_moves():
    st = _store()
    st.create_gateway(gw_id="a1", label="House", host="192.0.2.10")
    st.create_gateway(gw_id="b2", label="Garage", host="192.0.2.20")
    assert st.lock_gateway_serial("a1", "SN-A") == ("locked", "SN-A")
    assert st.gateway("a1")["serial"] == "SN-A"
    assert st.lock_gateway_serial("a1", "sn-a") == ("ok", "SN-A")
    assert st.lock_gateway_serial("a1", "SN-B") == ("mismatch", "SN-A")
    assert st.lock_gateway_serial("b2", "SN-A") == ("duplicate", "a1")
    assert st.gateway("b2")["serial"] == ""
    assert st.lock_gateway_serial("nope", "SN-C") == ("unregistered", "")


def test_the_database_refuses_a_second_gateway_with_the_same_serial():
    st = _store()
    st.create_gateway(gw_id="a1", label="House", host="192.0.2.10")
    st.create_gateway(gw_id="b2", label="Garage", host="192.0.2.20")
    st.lock_gateway_serial("a1", "SN-A")
    try:
        st._conn.execute("UPDATE gateways SET serial='SN-A' WHERE id='b2'")
        raise AssertionError("unique index missing")
    except sqlite3.IntegrityError:
        pass


def test_migration_adds_the_serial_column_to_an_existing_roster(tmp_path):
    p = tmp_path / "old.db"
    con = sqlite3.connect(p)
    con.execute("""CREATE TABLE gateways(id TEXT PRIMARY KEY, label TEXT NOT NULL,
                   host TEXT NOT NULL DEFAULT '', port INTEGER NOT NULL DEFAULT 9000,
                   is_default INTEGER NOT NULL DEFAULT 0, enabled INTEGER NOT NULL DEFAULT 1,
                   is_mock INTEGER NOT NULL DEFAULT 0, mock_seed INTEGER,
                   mock_units INTEGER NOT NULL DEFAULT 1, publish_ha INTEGER NOT NULL DEFAULT 1,
                   description TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL DEFAULT 0,
                   updated_at REAL NOT NULL DEFAULT 0)""")
    con.execute("INSERT INTO gateways(id,label,host) VALUES('old1','Home','192.0.2.10')")
    con.commit()
    con.close()
    st = db.MetricsStore(str(p))
    assert st.gateway("old1")["serial"] == ""                      # locks on first read
    assert st.lock_gateway_serial("old1", "SN-OLD") == ("locked", "SN-OLD")
    st.close()


def _poll(monkeypatch, gw, reported, seconds=2.5):
    # is_mock: no network-state or rediscovery reads against the documentation addresses
    inserts, notes, published = [], [], []
    s = config.get_settings()
    monkeypatch.setattr(s, "mqtt_enabled", False)
    monkeypatch.setattr(s, "poll_interval", 1)
    monkeypatch.setattr(poller.client, "firmware", lambda *a, **k: {"IBG_SN": reported})
    monkeypatch.setattr(poller.client, "summary", lambda *a, **k: {
        "ok": True, "power": {"soc": 50}, "firmware": {"IBG_SN": reported}})
    monkeypatch.setattr(db.MetricsStore, "insert", lambda self, *a, **k: inserts.append(a))
    monkeypatch.setattr(poller.Notifier, "notify", lambda self, t, m: notes.append((t, m)))

    async def go():
        stop = asyncio.Event()
        t = asyncio.create_task(poller.run_gateway(s, gw, stop))
        await asyncio.sleep(seconds)
        stop.set()
        await asyncio.wait_for(t, timeout=10)
    asyncio.run(go())
    return inserts, notes


def test_a_changed_serial_stops_the_gateway(monkeypatch):
    st = _store()
    st.create_gateway(gw_id="a1", label="House", host="192.0.2.10")
    st.lock_gateway_serial("a1", "SN-A")
    gw = GatewayState(id="a1", label="House", configured_host="192.0.2.10",
                      active_host="192.0.2.10", serial="SN-A", serial_locked=True,
                      is_mock=True)
    inserts, notes = _poll(monkeypatch, gw, "SN-B")
    assert inserts == []                                   # nothing recorded
    assert gw.serial == "SN-A"                             # never overwritten
    assert "SN-A" in gw.identity_error and "SN-B" in gw.identity_error
    assert [t for t, _ in notes] == ["FranklinWH gateway stopped"]


def test_a_serial_another_gateway_owns_is_refused(monkeypatch):
    st = _store()
    st.create_gateway(gw_id="a1", label="House", host="192.0.2.10")
    st.create_gateway(gw_id="b2", label="Garage", host="192.0.2.20")
    st.lock_gateway_serial("a1", "SN-A")
    gw = GatewayState(id="b2", label="Garage", configured_host="192.0.2.20",
                      active_host="192.0.2.20", is_mock=True)
    inserts, notes = _poll(monkeypatch, gw, "SN-A")
    assert inserts == [] and "a1" in gw.identity_error
    assert st.gateway("b2")["serial"] == ""


def test_first_report_locks_and_polling_goes_on(monkeypatch, caplog):
    st = _store()
    st.create_gateway(gw_id="a1", label="House", host="192.0.2.10")
    gw = GatewayState(id="a1", label="House", configured_host="192.0.2.10",
                      active_host="192.0.2.10", is_mock=True)
    inserts, notes = _poll(monkeypatch, gw, "SN-A")
    assert st.gateway("a1")["serial"] == "SN-A" and gw.serial_locked
    assert gw.identity_error is None and inserts and notes == []
    assert "poll failed" not in caplog.text            # the whole cycle ran, not just the insert


def test_a_stopped_gateway_is_refused_by_the_api():
    gw = state.register_gateway("a1", "192.0.2.10", "House")
    gw.identity_error = "aGate SN-A at 192.0.2.10 already belongs to gateway b2."
    try:
        c = TestClient(app_module.create_app())
        r = c.get("/api/power?gateway=a1")
        assert r.status_code == 409 and "belongs to gateway b2" in r.json()["detail"]
        roster = {g["id"]: g for g in c.get("/api/gateways").json()}
        assert roster["a1"]["identity_error"] == gw.identity_error
    finally:
        state.unregister_gateway("a1")


def test_no_gateway_gets_its_host_as_an_id_when_the_roster_is_unreadable(monkeypatch):
    s = config.get_settings()
    monkeypatch.setattr(s, "fwh_host", "192.0.2.99")
    monkeypatch.setattr(s, "fwh_cloud_email", "")
    monkeypatch.setattr(s, "fwh_cloud_password", "")
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)

    def boom(*a, **k):
        raise sqlite3.OperationalError("disk I/O error")
    monkeypatch.setattr(db.MetricsStore, "seed_gateways", boom)
    before = {g.id for g in state.gateways()}
    with TestClient(app_module.create_app()):
        assert state.get_gateway("192.0.2.99") is None
    for g in state.gateways():
        if g.id not in before:
            state.unregister_gateway(g.id)


def test_a_disabled_gateway_still_shows_its_locked_serial():
    st = _store()
    st.create_gateway(gw_id="d1", label="Shed", host="192.0.2.30", enabled=False)
    st.lock_gateway_serial("d1", "SN-D")
    c = TestClient(app_module.create_app())
    row = {g["id"]: g for g in c.get("/api/gateways").json()}["d1"]
    assert row["serial"] == "SN-D" and row["identity_error"] is None
