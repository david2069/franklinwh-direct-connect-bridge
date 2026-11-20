"""Which API reads each web UI tab needs, for custom roles (standalone installs only).

A custom role names the tabs it may open. Its reads are then the shared ones (what every
page loads: the top bar, the sidebar, alerts, the gateway selector) plus the reads of
its tabs; anything else gets 403. The built-in roles (admin, user, viewer, api) don't
use this. Entries are path prefixes, matched as ``security._under`` does.

``tests/test_tab_access.py`` keeps this in step with the UI: every ``api/…`` path a tab's
script or template calls must be allowed for that tab, and every GET route must be
shared, belong to a tab, or be listed as admin only.
"""

from __future__ import annotations

#: The tabs a custom role can be given, in sidebar order, with their labels.
TABS: dict[str, str] = {
    "dashboard": "Dashboard", "systemview": "System view", "battery": "Battery",
    "analytics": "Analytics", "energy_costs": "Billing & Utilities", "solar": "Solar",
    "scheduler": "Scheduler", "circuits": "Smart Circuits", "generator": "Generator",
    "health": "Health", "ha": "Home Assistant", "mqtt": "MQTT", "network": "Network",
    "grid": "Grid & Inverter", "device": "Device", "control": "Control", "logs": "Logs",
    "settings": "Settings",
}

#: Loaded on every page, whatever the tab: allowed for every custom role.
SHARED_READS: tuple[str, ...] = (
    "/api/version", "/api/live", "/api/auth", "/api/disclaimer", "/api/guide",
    "/api/gateways", "/api/site", "/api/host/timezone", "/api/setup", "/api/system-setup",
    "/api/schema", "/api/catalog", "/api/alerts", "/api/status", "/api/summary",
    "/api/capabilities", "/api/providers", "/api/constants", "/api/battery/command",
    "/api/offgrid/status", "/api/generator",
)

#: Each tab's own reads.
TAB_READS: dict[str, tuple[str, ...]] = {
    "dashboard": ("/api/metrics", "/api/energy", "/api/analytics/cloud",
                  "/api/solar/forecast", "/api/cmd", "/api/power"),
    "systemview": ("/api/system",),
    "battery": ("/api/battery", "/api/metrics", "/api/wear", "/api/apower-specs"),
    "analytics": ("/api/analytics", "/api/metrics", "/api/energy"),
    "energy_costs": ("/api/billing", "/api/tariffs", "/api/tariff", "/api/utilities",
                     "/api/meters", "/api/prices", "/api/sites"),
    "solar": ("/api/solar", "/api/metrics", "/api/energy"),
    "scheduler": ("/api/schedules", "/api/scheduler", "/api/cloud/tou", "/api/ha/notify-targets",
                  "/api/ha/notify-devices", "/api/ha/instances", "/api/ha/entities"),
    "circuits": ("/api/circuits", "/api/cloud/smart-circuits"),
    "generator": ("/api/generator",),
    "health": ("/api/health", "/api/firmware", "/api/diagnostics", "/api/troubleshoot"),
    "ha": ("/api/ha",),
    "mqtt": ("/api/mqtt",),
    "network": ("/api/network", "/api/health/link", "/api/cloud/pop", "/api/cloud/network",
                "/api/diagnostics"),
    "grid": ("/api/grid",),
    "device": ("/api/device", "/api/raw", "/api/cmd", "/api/der-comms", "/api/install-profile",
               "/api/apower-specs"),
    "control": ("/api/modbus", "/api/control-log", "/api/offgrid", "/api/cloud/mode",
                "/api/cloud/reserves", "/api/cmd", "/api/der-comms"),
    "logs": ("/api/logs",),
    "settings": ("/api/settings", "/api/security", "/api/sites", "/api/solar", "/api/hems",
                 "/api/integrations", "/api/notify", "/api/wear", "/api/tariffs",
                 "/api/tariff", "/api/utilities", "/api/meters", "/api/prices",
                 "/api/support-info", "/api/apower-specs", "/api/metrics/info",
                 "/api/ha", "/api/cloud", "/api/install-profile", "/api/modbus", "/api/mqtt"),
}

#: Reads no custom role gets, whatever its tabs: backups, exports, raw stores and the
#: account lists. (``security.ADMIN_READS`` are refused before this is consulted.)
ADMIN_ONLY_READS: tuple[str, ...] = (
    "/api/admin", "/api/security/users", "/api/security/signins", "/api/security/tokens",
    "/api/security/certificate", "/api/metrics/raw", "/api/solar/raw", "/api/circuits/raw",
    "/api/generator/raw", "/api/raw/catalog",
)


def _under(path: str, prefixes) -> bool:
    return any(path == p.rstrip("/") or path.startswith(p.rstrip("/") + "/") for p in prefixes)


def read_allowed(tabs, path: str) -> bool:
    """Whether a custom role with ``tabs`` may GET ``path``."""
    if _under(path, ADMIN_ONLY_READS):
        return False
    if _under(path, SHARED_READS):
        return True
    return any(_under(path, TAB_READS.get(t, ())) for t in tabs)
