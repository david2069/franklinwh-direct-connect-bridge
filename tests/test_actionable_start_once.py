"""The app starts the actionable Notifier once: a second start orphans a tap listener."""

from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import actionable, app as app_module


def test_the_lifespan_starts_actionable_notifications_once(monkeypatch):
    calls = []

    async def fake_start(store, settings):
        calls.append(store)
        return None

    async def fake_stop():
        return None

    monkeypatch.setattr(actionable, "start", fake_start)
    monkeypatch.setattr(actionable, "stop", fake_stop)
    try:
        with TestClient(app_module.create_app()):
            pass
    except Exception:  # noqa: BLE001 - shutdown noise is not what this test checks
        pass
    assert len(calls) == 1
