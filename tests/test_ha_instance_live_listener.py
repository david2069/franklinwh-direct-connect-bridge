"""An HA instance added, edited or removed in Settings gets (or loses) its tap listener at
once, without a bridge restart (franklinwh-ha-notify#5, 0.1.3).

Before: the Notifier's listeners were fixed at start-up, so buttons sent through a new
instance did nothing until the bridge restarted, and a deleted one kept listening.
"""
import asyncio
import threading
import types

import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import (actionable, app as app_module, config, db,
                                              environment, ha_supervisor)
from franklinwh_direct_connect_bridge.db import MetricsStore

#: Nothing listens here: the listener is created and keeps retrying, which is all the
#: tests need to see.
NOWHERE = "http://127.0.0.1:9"


@pytest.fixture
def store(tmp_path, monkeypatch):
    st = MetricsStore(str(tmp_path / "m.db"))
    monkeypatch.setattr(environment, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "_settings", None)
    monkeypatch.setattr(db, "get_store", lambda s: st)
    st.create_ha_instance(ha_id="home", name="Home", base_url=NOWHERE, token="t1",
                          is_default=True)
    return st


@pytest.fixture
def running(store):
    """The Notifier running on its own loop, as on the app's loop in the bridge."""
    loop = asyncio.new_event_loop()
    t = threading.Thread(target=loop.run_forever, daemon=True)
    t.start()

    def on_loop(coro):
        return asyncio.run_coroutine_threadsafe(coro, loop).result(5)
    on_loop(actionable.start(store, types.SimpleNamespace(ha_notify=True)))

    async def status():
        return actionable.notifier().listener_status()
    yield lambda: on_loop(status())
    on_loop(actionable.stop())
    loop.call_soon_threadsafe(loop.stop)
    t.join(5)
    loop.close()


def test_an_added_instance_gets_a_listener_without_a_restart(running):
    assert set(running()) == {"home"}
    c = TestClient(app_module.create_app())
    hid = c.post("/api/ha/instances", json={"name": "Shed", "base_url": NOWHERE,
                                            "token": "t2"}).json()["id"]
    assert set(running()) == {"home", hid}
    assert hid in actionable.notifier().instances


def test_a_disabled_or_deleted_instance_stops_listening(running):
    c = TestClient(app_module.create_app())
    hid = c.post("/api/ha/instances", json={"name": "Shed", "base_url": NOWHERE,
                                            "token": "t2"}).json()["id"]
    assert c.patch("/api/ha/instances/home", json={"enabled": False}).status_code == 200
    assert set(running()) == {hid}
    assert c.patch("/api/ha/instances/home", json={"enabled": True}).status_code == 200
    assert set(running()) == {"home", hid}
    assert c.delete(f"/api/ha/instances/{hid}").status_code == 200
    assert set(running()) == {"home"}
    assert hid not in actionable.notifier().instances


def test_an_edit_and_the_addon_token_refresh_tell_the_notifier(store, monkeypatch):
    calls = []
    monkeypatch.setattr(actionable, "sync_instances", lambda st: calls.append(st))
    c = TestClient(app_module.create_app())
    assert c.patch("/api/ha/instances/home",
                   json={"base_url": "http://127.0.0.1:10", "token": "t9"}).status_code == 200
    assert calls == [store]

    # The add-on's own instance: a new container brings a new Supervisor token (#99).
    store.update_ha_instance("home", base_url=ha_supervisor.SUPERVISOR_CORE_API, token="old")
    monkeypatch.setattr(ha_supervisor, "IS_HA_ADDON", True)
    monkeypatch.setenv("SUPERVISOR_TOKEN", "new-container-token")
    app_module._seed_self_ha_instance(config.get_settings())
    assert calls == [store, store]


def test_sync_is_a_no_op_when_notifications_are_not_running(store):
    assert actionable.notifier() is None
    actionable.sync_instances(store)              # never raises
