"""#374 foundation: one franklinwh-ha-notify Notifier over the store's HA instances."""

import asyncio
import sqlite3
import types

import pytest

from franklinwh_ha_notify import Event, Target

from franklinwh_direct_connect_bridge import actionable, db


def _store(tmp_path):
    st = db.MetricsStore(str(tmp_path / "bridge.db"))
    st.create_ha_instance(ha_id="home", name="Home", base_url="http://ha.test:8123",
                          token="t1", is_default=True)
    st.create_ha_instance(ha_id="off", name="Off", base_url="http://off.test:8123",
                          token="t2", enabled=False)
    return st


def test_the_store_creates_the_ledger_table(tmp_path):
    st = db.MetricsStore(str(tmp_path / "bridge.db"))
    names = {r[0] for r in st._conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "notify_ledger" in names


def test_enabled_instances_only_and_the_token_is_read_live(tmp_path):
    st = _store(tmp_path)
    n = actionable.build(st, types.SimpleNamespace(ha_notify=True))
    assert list(n.instances) == ["home"]
    assert n.instances["home"].bearer() == "t1"
    st.update_ha_instance("home", token="t-new")      # Supervisor refresh after an update (#99)
    assert n.instances["home"].bearer() == "t-new"


def test_the_master_switch_stops_sends_and_the_ledger_says_so(tmp_path):
    st = _store(tmp_path)
    settings = types.SimpleNamespace(ha_notify=False)
    n = actionable.build(st, settings)
    actionable.templates().register(Event("foundation_test", "T {gateway}", "M"))
    res = asyncio.run(n.notify("foundation_test", [Target("home", "mobile_app_x", "X")],
                               gateway="Home"))
    assert res.delivered == 0
    row = st._conn.execute("SELECT direction, status FROM notify_ledger").fetchone()
    assert row == ("SKIPPED", "notifications are off")


def test_start_and_stop(tmp_path):
    st = db.MetricsStore(str(tmp_path / "bridge.db"))           # no HA instance: nothing to listen on

    async def run():
        n = await actionable.start(st, types.SimpleNamespace(ha_notify=True))
        assert n is actionable.notifier() and n.instances == {}
        await actionable.stop()
        assert actionable.notifier() is None
    asyncio.run(run())
    assert asyncio.run(actionable.start(None, None)) is None


def test_stop_closes_the_notifiers_database_connection(tmp_path):
    st = db.MetricsStore(str(tmp_path / "bridge.db"))

    async def run():
        n = await actionable.start(st, types.SimpleNamespace(ha_notify=True))
        await actionable.stop()
        return n
    n = asyncio.run(run())
    with pytest.raises(sqlite3.ProgrammingError):     # closed, not left to the GC
        n.ledger.record("SENT", "x")
