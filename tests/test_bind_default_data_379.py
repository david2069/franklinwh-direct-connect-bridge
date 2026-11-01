"""#379 part 3b: nothing is saved for "no gateway" any more.

Before #379 a schedule could be left on no gateway (it ran on the default), and billing and
System Setup saved under the key "default". ``adopt_default_data`` gives that data to the
default gateway, at start-up and when the first gateway is added. Saving a schedule now needs
a known gateway, an import binds to the gateway it is imported into, and a schedule that is
still unbound runs nowhere.
"""
import datetime as dt
import json

import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import app as app_module
from franklinwh_direct_connect_bridge import billing, db, mockgw, scheduler, state, supervisor
from franklinwh_direct_connect_bridge import client as client_module
from franklinwh_direct_connect_bridge import system_setup


@pytest.fixture(autouse=True)
def _fresh():
    state.reset_gateways()
    yield
    state.reset_gateways()


@pytest.fixture
def st(tmp_path):
    return db.MetricsStore(str(tmp_path / "m.db"))


@pytest.fixture
def c(st, monkeypatch):
    monkeypatch.setattr(db, "get_store", lambda *a, **k: st)

    async def _noop(*a, **k):
        return None
    monkeypatch.setattr(supervisor, "start_poller", _noop)
    monkeypatch.setattr(supervisor, "stop_poller", _noop)
    monkeypatch.setattr(supervisor, "is_running", lambda gid: False)
    monkeypatch.setattr(mockgw, "start_mock", lambda gid, **k: "127.0.0.1:59999")
    monkeypatch.setattr(mockgw, "stop_mock", lambda gid: None)
    monkeypatch.setattr(client_module, "writes_enabled", lambda s: True)
    return TestClient(app_module.create_app())


def _add(c, label, host):
    r = c.post("/api/gateways", json={"label": label, "host": host})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _unbound(st, sid="s-old"):
    """A schedule saved before #379 with no gateway."""
    st.create_schedule(sid=sid, name="old", spec={"fire_at": "18:00", "gateway_id": "",
                                                  "action": {"kind": "notify"}}, enabled=False)


# ── the store migration ─────────────────────────────────────────────────────

def test_adopt_binds_schedules_keys_and_periods(st):
    _unbound(st)
    st.create_schedule(sid="s-own", name="own", spec={"gateway_id": "other"}, enabled=False)
    st.set_config("billing_state:default", json.dumps({"period_start": 1}))
    st.set_config("system_setup:default", json.dumps({"solar_kwp": 6.6}))
    st._conn.execute("INSERT INTO billing_periods(closed_at, gateway_id) VALUES (1, NULL)")
    st._conn.commit()

    moved = st.adopt_default_data("gwA")

    assert moved == {"schedules": 1, "keys": ["billing_state", "system_setup"],
                     "billing_periods": 1}
    assert st.schedule("s-old")["gateway_id"] == "gwA"
    assert st.schedule("s-own")["gateway_id"] == "other"        # its own gateway kept
    assert st.get_config("billing_state:default") is None
    assert json.loads(st.get_config("system_setup:gwA")) == {"solar_kwp": 6.6}
    assert st.billing_periods()[0]["gateway_id"] == "gwA"
    assert st.adopt_default_data("gwA") == {"schedules": 0, "keys": [], "billing_periods": 0}


def test_adopt_never_overwrites_the_gateways_own_data(st):
    st.set_config("system_setup:default", json.dumps({"solar_kwp": 1.0}))
    st.set_config("system_setup:gwA", json.dumps({"solar_kwp": 9.9}))
    assert st.adopt_default_data("gwA")["keys"] == []
    assert json.loads(st.get_config("system_setup:gwA")) == {"solar_kwp": 9.9}
    assert st.get_config("system_setup:default") is not None   # left as it was


def test_the_first_gateway_takes_the_unbound_schedules(c, st):
    _unbound(st)
    a = _add(c, "A", "10.0.0.1")
    assert st.schedule("s-old")["gateway_id"] == a
    _unbound(st, "s-later")                    # a second gateway does not take anything
    _add(c, "B", "10.0.0.2")
    assert st.schedule("s-later")["gateway_id"] == ""


def test_start_up_binds_to_the_default_gateway(st, monkeypatch):
    st.create_gateway(gw_id="gA", label="A", host="10.0.0.1", port=9000, is_default=True,
                      enabled=True, is_mock=False, mock_seed=None, mock_units=1,
                      publish_ha=False, description="")
    _unbound(st)
    monkeypatch.setattr(db, "get_store", lambda *a, **k: st)

    async def _noop(*a, **k):
        return None
    monkeypatch.setattr(supervisor, "start_poller", _noop)
    from franklinwh_direct_connect_bridge import battery_control
    # start-up sets the Modbus client switch from this store; keep it from leaking
    monkeypatch.setattr(battery_control, "_ENABLED", battery_control._ENABLED)
    with TestClient(app_module.create_app()):
        pass
    assert st.schedule("s-old")["gateway_id"] == "gA"


# ── saving and importing schedules ──────────────────────────────────────────

_ACT = {"kind": "force", "direction": "charge", "unit": "pct", "power": 80, "target_soc": 90}
_BODY = {"name": "x", "fire_at": "18:00", "duration_min": 60,
         "conditions": [{"sensor": "battery.soc_pct", "op": "<", "value": 20}], "action": _ACT}


def test_a_schedule_needs_a_gateway(c):
    _add(c, "A", "10.0.0.1")
    r = c.post("/api/schedules", json=_BODY)
    assert r.status_code == 422 and "choose the gateway" in r.json()["detail"]


def test_a_schedule_on_an_unknown_gateway_is_refused(c):
    _add(c, "A", "10.0.0.1")
    r = c.post("/api/schedules", json={**_BODY, "gateway_id": "nope"})
    assert r.status_code == 422 and "unknown gateway 'nope'" in r.json()["detail"]


def test_a_schedule_on_a_known_gateway_saves(c):
    a = _add(c, "A", "10.0.0.1")
    r = c.post("/api/schedules", json={**_BODY, "gateway_id": a})
    assert r.status_code == 201 and r.json()["gateway_id"] == a


def test_import_binds_to_the_gateway_imported_into(c, st):
    a, b = _add(c, "A", "10.0.0.1"), _add(c, "B", "10.0.0.2")
    bundle = {"type": scheduler.EXPORT_TYPE, "entries": [
        {**_BODY, "name": "none"},
        {**_BODY, "name": "foreign", "gateway_id": "elsewhere"},
        {**_BODY, "name": "own", "gateway_id": a}]}
    assert c.post("/api/schedules/import?dry_run=false", json=bundle).status_code == 400
    r = c.post(f"/api/schedules/import?dry_run=false&gateway={b}", json=bundle)
    assert r.status_code == 200, r.text
    got = {s["name"]: s["gateway_id"] for s in st.schedules()}
    assert got == {"none": b, "foreign": b, "own": a}


# ── what still has no gateway runs nowhere ──────────────────────────────────

def test_an_unbound_schedule_does_not_run_on_the_default(st, monkeypatch):
    """Before #379 it ran on the default gateway's tick; now it runs nowhere."""
    st.create_schedule(sid="s1", name="Shed", spec={
        "gateway_id": "", "fire_at": "18:00", "duration_min": 90, "conditions": [],
        "action": {}, "ha_actions": []})
    state.register_gateway("gA", "192.0.2.10", "A")
    state.set_default("gA")
    monkeypatch.setattr(scheduler, "ha_snapshot", lambda store: {})
    fired = scheduler.tick(settings=None, client=None, store=st, state={},
                           gateway_id="gA", now=dt.datetime(2026, 9, 15, 18, 30))
    assert fired == []


# ── billing and System Setup are kept per gateway ───────────────────────────

def test_billing_needs_a_gateway():
    with pytest.raises(ValueError):
        billing._gw_key(None)
    with pytest.raises(ValueError):
        billing._gw_key("")
    assert billing._gw_key("gwA") == "gwA"


def test_system_setup_is_saved_under_the_gateway(st):
    with pytest.raises(ValueError):
        system_setup.update(st, None, {"solar_kwp": 5})
    system_setup.update(st, "gwA", {"solar_kwp": 5})
    assert st.get_config("system_setup:gwA") is not None
    assert st.get_config("system_setup:default") is None
