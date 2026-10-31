"""#379 part 3b-ii: no call falls back to the default gateway's host.

``client.*`` raises on an empty host instead of using ``fwh_host`` or the default gateway,
``get_state()`` no longer registers a gateway on first use, ``FWH_MODBUS_HOST`` is not read,
the poller passes ``active_host or configured_host``, and a scheduler tick for no gateway
evaluates nothing.
"""
import asyncio
import datetime as dt

import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import app as app_module
from franklinwh_direct_connect_bridge import config, db, poller, scheduler, state
from franklinwh_direct_connect_bridge.config import Settings
from franklinwh_direct_connect_bridge.state import GatewayState


@pytest.fixture(autouse=True)
def _fresh():
    state.reset_gateways()
    yield
    state.reset_gateways()


@pytest.fixture
def c(tmp_path, monkeypatch):
    st = db.MetricsStore(str(tmp_path / "m.db"))
    monkeypatch.setattr(db, "get_store", lambda *a, **k: st)
    return TestClient(app_module.create_app())


def test_a_configured_host_is_not_registered_on_first_use(c, monkeypatch):
    """The roster is what start-up registered; a read never invents the default gateway."""
    monkeypatch.setattr(config, "get_settings", lambda: Settings(fwh_host="10.0.0.9"))
    monkeypatch.setattr(app_module, "get_settings", lambda: Settings(fwh_host="10.0.0.9"))
    monkeypatch.setattr(db, "get_store", lambda *a, **k: None)
    assert c.get("/api/gateways").json() == []
    assert state.gateways() == []


def test_settings_host_is_the_named_gateways_and_none_without_one(c):
    state.register_gateway("gw-a", "10.0.0.1", "A")
    b = state.register_gateway("gw-b", "10.0.0.2", "B")
    b.active_host = "10.0.0.22"                 # re-discovered
    state.set_default("gw-a")
    assert c.get("/api/settings?gateway=gw-b").json()["connection"]["host"] == "10.0.0.22"
    assert c.get("/api/settings").json()["connection"]["host"] is None


def test_a_tick_for_no_gateway_evaluates_nothing(tmp_path, monkeypatch):
    from franklinwh_direct_connect_bridge import battery_control as bc
    ran = []
    monkeypatch.setattr(bc, "execute", lambda cmd, **kw: ran.append(cmd) or
                        {"ok": True, "result": "ok", "active": cmd})
    st = db.MetricsStore(str(tmp_path / "m.db"))
    st.create_schedule(sid="all", name="every gateway", spec={
        "gateway_scope": "all", "fire_at": "14:00", "duration_min": 60,
        "action": {"kind": "force", "direction": "discharge", "unit": "pct", "power": 50}})
    scheduler._window_inside.clear()
    fired = scheduler.tick(settings=None, client=None, store=st, state={"soc": 50},
                           host="h", gateway_id=None, now=dt.datetime(2026, 9, 22, 14, 10))
    assert fired == [] and ran == []


def test_the_poller_reads_the_configured_host_when_none_was_rediscovered(monkeypatch):
    hosts = []
    s = config.get_settings()
    monkeypatch.setattr(s, "mqtt_enabled", False)
    monkeypatch.setattr(s, "poll_interval", 1)
    monkeypatch.setattr(poller.client, "firmware",
                        lambda _s, host=None: hosts.append(host) or {"IBG_SN": "", "IBG_VER": "V1"})
    monkeypatch.setattr(poller.client, "summary",
                        lambda _s, host=None, **k: hosts.append(host) or {"ok": False})
    gw = GatewayState(id="g1", label="house", configured_host="192.0.2.10", active_host=None)

    async def go():
        stop = asyncio.Event()
        t = asyncio.create_task(poller.run_gateway(s, gw, stop))
        await asyncio.sleep(1.5)
        stop.set()
        await asyncio.wait_for(t, timeout=10)
    asyncio.run(go())
    assert hosts and set(hosts) == {"192.0.2.10"}
