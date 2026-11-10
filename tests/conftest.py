"""Global test isolation.

A test once truncated the live bridge's log file because it logged + called
``logbuffer.clear()`` WITHOUT redirecting ``DATA_DIR`` — and docker-compose mounts
``./data:/data``, so the host default ``./data`` IS the running bridge's data dir.
This autouse fixture makes that impossible: every test gets a fresh tmp ``DATA_DIR``
and a settings singleton pinned to a tmp ``metrics_db`` (its default is an absolute
``/data/metrics.db``), and the store cache + log buffer are reset around each test.

A test that specifically needs the real defaults can opt out with
``@pytest.mark.real_data_dir``.
"""

import pytest

from franklinwh_direct_connect_bridge import environment, config, db, logbuffer, security


def pytest_configure(config):  # noqa: ARG001 — pytest hook
    config.addinivalue_line("markers",
                            "real_data_dir: run without the tmp DATA_DIR isolation")
    config.addinivalue_line("markers",
                            "security_on: keep the Security switch as the store says (#457)")


@pytest.fixture(autouse=True)
def _isolate_data_dir(request, tmp_path, monkeypatch):
    if request.node.get_closest_marker("real_data_dir"):
        yield
        return
    monkeypatch.setattr(environment, "DATA_DIR", str(tmp_path))
    # Pin settings to a tmp metrics DB — the default is an absolute /data/metrics.db, so
    # DATA_DIR alone would not stop a store from opening the real (mounted) database.
    monkeypatch.setattr(config, "_settings", None)
    s = config.get_settings()
    monkeypatch.setattr(s, "metrics_db", str(tmp_path / "metrics.db"))
    monkeypatch.setattr(config, "_settings", s)
    db.reset_store()
    logbuffer.set_store(None)
    logbuffer.clear()
    # The cloud sign-in hold is process state persisted under DATA_DIR: start every test
    # with it off and unloaded, so one test's rejection can't hold the next test's logins.
    from franklinwh_direct_connect_bridge import providers
    monkeypatch.setattr(providers, "_hold", {"active": False, "message": "", "since": 0.0,
                                             "account": ""})
    monkeypatch.setattr(providers, "_hold_loaded", True)
    yield
    db.reset_store()
    logbuffer.set_store(None)


@pytest.fixture
def fake_notifier(monkeypatch):
    """Start the one Notifier (#374) on a store, with Home Assistant faked: each send is
    recorded in the returned list and every target on a known instance accepts it.
    ``fake_notifier(store, on=False)`` starts it with Push notifications off. As in the
    app, it lives on an event loop of its own that worker threads reach with submit()."""
    import asyncio
    import threading
    import types

    from franklinwh_ha_notify import notifier as _n
    from franklinwh_ha_notify.send import Delivery, SendResult

    from franklinwh_direct_connect_bridge import actionable

    sends: list[dict] = []

    async def fake_send(instances, targets, title, message, buttons=None, request_id=None):
        sends.append({"targets": [t.key for t in targets], "title": title, "message": message})
        return SendResult([Delivery(t.key, t.instance_id in instances,
                                          "" if t.instance_id in instances else "unknown HA instance")
                              for t in targets])

    monkeypatch.setattr(_n, "send", fake_send)

    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()

    def start(store, *, on: bool = True):
        settings = types.SimpleNamespace(ha_notify=on)
        monkeypatch.setattr(actionable, "_notifier", actionable.build(store, settings))
        monkeypatch.setattr(actionable, "_loop", loop)
        start.settings = settings
        return sends
    yield start
    loop.call_soon_threadsafe(loop.stop)
    thread.join(5)
    loop.close()


_REAL_SECURITY_ENABLED = security.enabled


@pytest.fixture(autouse=True, scope="session")
def _security_off():
    """Every test store is a new install, which turns Security on (#457 phase 3) and would
    send the test client to sign in. Session-wide, so module-scoped app fixtures get it
    too. Tests of Security mark themselves ``security_on``."""
    mp = pytest.MonkeyPatch()
    mp.setattr(security, "enabled", lambda store: False)
    yield
    mp.undo()


@pytest.fixture(autouse=True)
def _security_on_when_marked(request, monkeypatch):
    if request.node.get_closest_marker("security_on"):
        monkeypatch.setattr(security, "enabled", _REAL_SECURITY_ENABLED)


@pytest.fixture(autouse=True)
def _drop_dead_pollers():
    """A test client whose event loop ends without the app's shutdown (a request that
    added a gateway, outside ``with TestClient``) leaves its poller tasks cancelled in
    the supervisor's module-level maps and the worker registry. The next app's shutdown
    then awaited one and re-raised its CancelledError, and its supervisor restarted the
    dead pollers on the new loop. Drop what has finished before each test; anything still
    running belongs to a live (module-scoped) app and is kept."""
    from franklinwh_direct_connect_bridge import supervisor, workers

    for gw_id, (task, _stop) in list(supervisor._pollers.items()):
        if task.done():
            supervisor._pollers.pop(gw_id, None)
    for d in (supervisor._stopping, supervisor._deferred):
        for gw_id, task in list(d.items()):
            if task.done():
                d.pop(gw_id, None)
    for w in workers.registry.all():
        if w.name.startswith("poller:") and w._task is not None and w._task.done():
            workers.registry.unregister(w.name)
    yield
