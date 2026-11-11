"""Non-actionable Home Assistant notifications (persistent_notification.create).

They go to the default enabled HA instance from Settings (#464); on the add-on that is its
own instance, reached through the Supervisor. Only with no instance set up does the
environment decide: the Supervisor's ``SUPERVISOR_TOKEN``, else ``ha_url``/``ha_token``.
These have no buttons. Phone pushes, with or without buttons, go through the one
franklinwh-ha-notify Notifier in ``actionable`` (#374).
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request

from .config import Settings


def _mb_port() -> int:
    from .battery_control import default_port
    return default_port()


log = logging.getLogger("franklinwh_direct_connect_bridge.notify")

#: The outbox record for a delivery not made because ha_notify is off (#271; the wording
#: is fixed by the owner's decision on franklinwh-modbus-bridge#324).
SKIPPED_CHANNEL_OFF = "skipped: HA channel off"


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
        """(enabled, token, base) resolved live, from :meth:`target_info`."""
        t = self.target_info()
        return t["enabled"], t["token"], t["base"]

    def _default_instance(self) -> dict | None:
        """The default enabled HA instance from Settings (#464); else the first enabled
        one (the roster lists the default first). None when no instance is enabled."""
        try:
            from . import db
            store = db.get_store(self.settings)
            rows = [r for r in (store.ha_instances() if store else [])
                    if r.get("enabled", 1) and r.get("base_url")]
        except Exception as e:  # noqa: BLE001 — fall back to the environment
            log.debug("HA instances not readable for notifications: %s", e)
            return None
        return next((r for r in rows if r.get("is_default")), rows[0] if rows else None)

    def target_info(self) -> dict:
        """Where persistent notifications go, resolved live (#464).

        The default enabled HA instance from Settings wins: on the add-on that is its own
        instance, "Home Assistant (this add-on)". Only when no instance is set up does the
        environment decide: the add-on's Supervisor token, else ``ha_url`` + ``ha_token``.
        ``source`` is ``instance`` / ``supervisor`` / ``environment`` / ``none``."""
        s = self.settings
        enabled = bool(getattr(s, "ha_notify", True))
        inst = self._default_instance()
        if inst is not None:
            return {"enabled": enabled, "source": "instance", "name": inst.get("name") or "",
                    "instance_id": inst["id"], "token": inst.get("token") or "",
                    "base": inst["base_url"].rstrip("/") + "/api"}
        supervisor = os.environ.get("SUPERVISOR_TOKEN")
        if supervisor:                                  # HA add-on mode
            return {"enabled": enabled, "source": "supervisor", "name": "", "instance_id": "",
                    "token": supervisor, "base": "http://supervisor/core/api"}
        if s.ha_url and s.ha_token:                     # standalone
            return {"enabled": enabled, "source": "environment", "name": "", "instance_id": "",
                    "token": s.ha_token, "base": s.ha_url.rstrip("/") + "/api"}
        return {"enabled": enabled, "source": "none", "name": "", "instance_id": "",
                "token": "", "base": ""}

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

    def call_service(self, domain: str, service: str, data: dict) -> str:
        """Call one HA service on the same target as notify(), and SAY what happened —
        the alert outbox (#271) needs to know whether to retry. Returns "" on success,
        "skipped: …" when there is nothing to call (no HA target, or ha_notify off),
        otherwise the error. Never raises."""
        enabled, token, base = self._target()
        if not enabled:
            return SKIPPED_CHANNEL_OFF
        if not (token and base):
            return "skipped: no Home Assistant API configured"
        try:
            req = urllib.request.Request(
                f"{base}/services/{domain}/{service}",
                data=json.dumps(data).encode(), method="POST",
                headers={"Authorization": f"Bearer {token}",
                         "Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=10)
            return ""
        except Exception as e:  # noqa: BLE001
            return str(e) or type(e).__name__


def transitions(prev: dict | None, cur: dict, gateway: str = "") -> list[tuple[str, str]]:
    """Notify only on state CHANGES (not every poll). Returns (title, message) pairs, each
    naming ``gateway`` (#361)."""
    if prev is None:
        return []
    out = []
    tag = f" [{gateway}]" if gateway else ""
    if prev.get("ok") != cur.get("ok"):
        out.append(("FranklinWH aGate",
                    f"aGate is reachable again{tag}." if cur.get("ok")
                    else f"aGate is UNREACHABLE{tag} (check network / WiFi / power)."))
    if prev.get("modbus_502") != cur.get("modbus_502"):
        out.append(("FranklinWH Modbus",
                    f"Modbus :{_mb_port()} is back up{tag}." if cur.get("modbus_502")
                    else f"Modbus :{_mb_port()} is DOWN{tag}."))
    return out
