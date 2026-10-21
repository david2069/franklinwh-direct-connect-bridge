"""Every notification is also a line in the app log, even with no devices (owner, 2026-10-21)."""

import logging
from pathlib import Path

from franklinwh_direct_connect_bridge import db, notify_engine
from franklinwh_direct_connect_bridge.config import get_settings


def test_a_notification_with_no_devices_is_in_the_app_log(caplog):
    store = db.get_store(get_settings())
    with caplog.at_level(logging.INFO, logger="franklinwh_direct_connect_bridge.notify_engine"):
        notify_engine.fire(store, "aGate_offline", "FranklinWH", "aGate is UNREACHABLE [gw]")
    rec = [r for r in caplog.records if "aGate is UNREACHABLE" in r.getMessage()]
    assert rec and rec[0].levelno == logging.WARNING
    assert store.notify_log(limit=1)[0]["device"] == "(no devices)"


def test_recent_notifications_put_the_time_first():
    html = (Path(notify_engine.__file__).parent / "templates/tabs/settings.html").read_text()
    row = html[html.index("Recent notifications (delivery log)"):html.index("<!-- Add-on note -->")]
    assert row.index("fmtNotifyTime(e.ts)") < row.index('x-text="e.message"') < row.index('x-text="e.device"')
