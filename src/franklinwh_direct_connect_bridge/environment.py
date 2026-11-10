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
