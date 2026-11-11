"""Which installation this is (owner, 2026-11-11), for the support info.

A random ``install_id`` (uuid4) and the ``first_version`` are written once to the bridge's
own store, next to ``install_date``, and never changed. The rest is read at the time:
how it was installed, the OS, CPU, Python and bridge version. Nothing here leaves the
bridge on its own; it is only shown in the support info the owner copies.

Install types: ``ha_addon_haos`` / ``ha_addon_supervised`` (``ha_addon`` when the
Supervisor doesn't answer), ``docker``, ``podman``, ``pip`` (installed package) and
``dev`` (run from a source checkout).
"""

from __future__ import annotations

import platform
import uuid
from pathlib import Path


def _exists(path: str) -> bool:
    return Path(path).exists()


def _source_checkout() -> bool:
    # src/franklinwh_direct_connect_bridge/ → the repo root holds pyproject.toml; an
    # installed wheel lives in site-packages with no pyproject beside it.
    return (Path(__file__).resolve().parents[2] / "pyproject.toml").exists()


def _supervisor_info() -> dict | None:
    from . import ha_supervisor
    return ha_supervisor.supervisor_info()


def install_type() -> str:
    if _exists("/data/options.json"):
        info = _supervisor_info()
        if info is None:
            return "ha_addon"
        return "ha_addon_haos" if info.get("hassos") else "ha_addon_supervised"
    if _exists("/run/.containerenv"):
        return "podman"
    if _exists("/.dockerenv"):
        return "docker"
    return "dev" if _source_checkout() else "pip"


def ensure(store, version: str) -> None:
    """Set the install id and first version on the first start; never overwrite them."""
    if store is None:
        return
    if not store.get_config("install_id"):
        store.set_config("install_id", str(uuid.uuid4()))
    if not store.get_config("first_version"):
        store.set_config("first_version", version)


def facts(store, version: str) -> dict:
    kind = install_type()
    info = (_supervisor_info() or {}) if kind.startswith("ha_addon") else {}
    return {
        "install_id": store.get_config("install_id") if store else None,
        "install_type": kind,
        "os": info.get("operating_system") or f"{platform.system()} {platform.release()}",
        "arch": platform.machine(),
        "python": platform.python_version(),
        "bridge_version": version,
        "install_date": store.get_config("install_date") if store else None,
        "first_version": store.get_config("first_version") if store else None,
        "home_assistant": info.get("homeassistant"),
    }
