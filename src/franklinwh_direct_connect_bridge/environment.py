"""Detect which runtime environment the bridge is running in.

- ``ha_addon`` — running as a Home Assistant Supervisor add-on (/data/options.json exists).
- ``docker``   — plain container: /.dockerenv (Docker) or /run/.containerenv (Podman, #491),
  and no add-on options.
- ``dev``      — running from a checkout on the host.

``DATA_DIR`` is where the bridge persists state (metrics DB, options env). The add-on
and docker map a ``/data`` volume; dev falls back to a local ``./data`` directory.
"""

from __future__ import annotations

from pathlib import Path


def _detect() -> str:
    if Path("/data/options.json").exists():
        return "ha_addon"
    # Podman makes /run/.containerenv instead of /.dockerenv (#491); missing it put a Podman
    # user's data in /app/data, outside the /data volume, lost when the container was recreated.
    if Path("/.dockerenv").exists() or Path("/run/.containerenv").exists():
        return "docker"
    return "dev"


RUNTIME: str = _detect()
IS_HA_ADDON: bool = RUNTIME == "ha_addon"
DATA_DIR: str = "/data" if RUNTIME in ("ha_addon", "docker") else "./data"


# ── Sign-in and accounts: one way or the other, never mixed (owner 2026-11-20) ────────
#: The Home Assistant add-on: HA users come in through the sidebar with their HA group's
#: role, and the first admin is made there. Standalone (Docker and pip): no HA users; the
#: first admin comes from the settings, the setup command or a generated password.
ACCOUNTS_HA = "home_assistant"
ACCOUNTS_STANDALONE = "standalone"
ACCOUNT_FEATURES: dict[str, tuple[str, ...]] = {
    ACCOUNTS_HA: (
        "ha_users",                     # sidebar (ingress) sign-in, role from the HA group
        "first_admin_in_sidebar",       # Settings → Admin → Security, from the sidebar
    ),
    ACCOUNTS_STANDALONE: (
        "first_admin_from_settings",    # ADMIN_USERNAME/ADMIN_PASSWORD, or generated
        "setup_command",                # franklinwh-direct-connect-bridge setup
        "settings_file",                # DATA_DIR/bridge.env
        "security_off_on_first_start",  # SECURITY=off quick start
        "startup_banner",               # addresses and the generated password, on start
        "custom_roles",                 # roles an admin defines (tabs and actions)
    ),
}


def accounts_mode() -> str:
    """Which way this install sets up sign-in and accounts. Read at call time so tests
    can monkeypatch ``IS_HA_ADDON``."""
    return ACCOUNTS_HA if IS_HA_ADDON else ACCOUNTS_STANDALONE


def account_feature(name: str) -> bool:
    """Whether ``name`` (a key of ``ACCOUNT_FEATURES``) applies to this install."""
    if not any(name in f for f in ACCOUNT_FEATURES.values()):
        raise KeyError(name)
    return name in ACCOUNT_FEATURES[accounts_mode()]
