"""Non-actionable Home Assistant notifications (persistent_notification.create).

In the HA add-on, the supervisor injects ``SUPERVISOR_TOKEN`` and proxies the core API at
``http://supervisor/core/api`` — zero user config. Standalone can set ``ha_url``/``ha_token``.
No actionable/interactive notifications (kept simple on purpose).
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request

from .config import Settings

log = logging.getLogger("franklinwh_local_bridge.notify")


class Notifier:
    def __init__(self, settings: Settings):
        # Hold the (singleton) settings and resolve the target at notify() time, so a live
        # UI edit of ha_url/ha_token/ha_notify applies to a long-lived notifier (e.g. the
        # poller's) without a restart.
        self.settings = settings

    # Exposed as live properties rather than attributes assigned inside notify().
    # They used to be created only when notify() first ran, so any caller that
    # inspected them beforehand — e.g. POST /api/notify/test checking whether a
    # target is configured — raised AttributeError and returned a 500.
    @property
    def enabled(self) -> bool:
        return self._target()[0]

    @property
    def token(self) -> str:
        return self._target()[1]

    @property
    def base(self) -> str:
        return self._target()[2]

    def _target(self) -> tuple[bool, str, str]:
        """(enabled, token, base) resolved live. Add-on Supervisor token wins; else the
        standalone ha_url + ha_token."""
        s = self.settings
        supervisor = os.environ.get("SUPERVISOR_TOKEN")
        if supervisor:                                  # HA add-on mode
            return s.ha_notify, supervisor, "http://supervisor/core/api"
        if s.ha_url and s.ha_token:                     # standalone
            return s.ha_notify, s.ha_token, s.ha_url.rstrip("/") + "/api"
        return s.ha_notify, "", ""

    def notify(self, title: str, message: str) -> None:
        # Resolve once per call into locals — the properties above re-read settings,
        # and we want one consistent view for this notification.
        enabled, token, base = self._target()
        if not (enabled and token and base):
            log.info("notify (no HA API): %s — %s", title, message)
            return
        try:
            data = json.dumps({"title": title, "message": message}).encode()
            req = urllib.request.Request(
                f"{base}/services/persistent_notification/create",
                data=data, method="POST",
                headers={"Authorization": f"Bearer {token}",
                         "Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=10)
        except Exception as e:  # noqa: BLE001 — a failed notify must never break the poll
            log.warning("HA notify failed: %s", e)


def transitions(prev: dict | None, cur: dict) -> list[tuple[str, str]]:
    """Notify only on state CHANGES (not every poll). Returns (title, message) pairs."""
    if prev is None:
        return []
    out = []
    if prev.get("ok") != cur.get("ok"):
        out.append(("FranklinWH aGate",
                    "aGate is reachable again." if cur.get("ok")
                    else "aGate is UNREACHABLE (check network / WiFi / power)."))
    if prev.get("modbus_502") != cur.get("modbus_502"):
        out.append(("FranklinWH Modbus",
                    "Modbus :502 is back up." if cur.get("modbus_502")
                    else "Modbus :502 is DOWN."))
    return out
