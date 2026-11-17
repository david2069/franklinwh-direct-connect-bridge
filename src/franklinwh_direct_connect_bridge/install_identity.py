"""Which installation this is (owner, 2026-11-11), for the support info.

A random ``install_id`` (uuid4) and the ``first_version`` are written once to the bridge's
own store, next to ``install_date``, and never changed. The rest is read at the time:
how it was installed, the OS, CPU, Python and bridge version. These are shown in the
support info the owner copies; :func:`bridge_version` (#706) also goes to Home Assistant
as the "Bridge Version" entity, without the install id or any other identifier.

Install types: ``ha_addon_haos`` / ``ha_addon_supervised`` (``ha_addon`` when the
Supervisor doesn't answer), ``docker``, ``podman``, ``pip`` (installed package) and
``dev`` (run from a source checkout).
"""

from __future__ import annotations

import platform
import re
import time
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


#: The bridge's distribution, whose dependencies name the libraries to report.
DIST = "franklinwh-direct-connect-bridge"
#: Shared packages without the ``franklinwh-`` prefix (the HEMS engine, #613).
SHARED = ("hems",)
#: How long the install type and HA version are reused: the Supervisor is asked at most
#: this often, not on every alert-monitor pass.
INSTALL_TTL_S = 600
_install_cache: dict = {}


def _dep_names() -> list[str]:
    """The names of every dependency, base and extras: the installed package's metadata,
    or pyproject.toml in a source checkout (its metadata may be an older install's)."""
    from importlib import metadata
    reqs: list[str] = []
    if _source_checkout():
        import tomllib
        proj = tomllib.loads((Path(__file__).resolve().parents[2] / "pyproject.toml")
                             .read_text())["project"]
        reqs = list(proj.get("dependencies") or []) + [
            d for v in (proj.get("optional-dependencies") or {}).values() for d in v]
    else:
        try:
            reqs = list(metadata.requires(DIST) or [])
        except metadata.PackageNotFoundError:
            reqs = []
    out = []
    for r in reqs:
        m = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", r)
        if m:
            out.append(m.group(1).lower().replace("_", "-"))
    return out


def libraries() -> dict[str, str | None]:
    """The installed version of each FranklinWH / shared library the bridge depends on;
    None when it isn't installed (an extra left out)."""
    from importlib import metadata
    out: dict[str, str | None] = {}
    for name in sorted(set(_dep_names())):
        if not (name.startswith("franklinwh-") or name in SHARED):
            continue
        try:
            out[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            out[name] = None
    return out


def _install(now: float) -> tuple[str, str | None, str | None]:
    if now - _install_cache.get("ts", float("-inf")) >= INSTALL_TTL_S:
        kind = install_type()
        info = (_supervisor_info() or {}) if kind.startswith("ha_addon") else {}
        _install_cache.update(ts=now, kind=kind, ha=info.get("homeassistant"),
                              os=info.get("operating_system"))
    return _install_cache["kind"], _install_cache.get("ha"), _install_cache.get("os")


def bridge_version(settings, store) -> dict:
    """The "Bridge Version" entity's payload (#706): the version, platform, install type,
    the integrations in use and the library versions. Counts and booleans only: no
    install id, serial, host, account or token."""
    from . import __version__, state
    kind, ha_version, ha_os = _install(time.monotonic())
    configured = bool(getattr(settings, "fwh_cloud_email", "")
                      and getattr(settings, "fwh_cloud_password", ""))
    try:
        from . import providers
        cloud_state = providers.cloud_auth_status().get("state") or "unknown"
    except Exception:  # noqa: BLE001
        cloud_state = "unknown"
    try:
        from . import battery_control
        modbus_on = bool(battery_control.is_enabled())
    except Exception:  # noqa: BLE001
        modbus_on = False
    try:
        ha_n = sum(1 for i in (store.ha_instances() if store else []) if i.get("enabled"))
    except Exception:  # noqa: BLE001
        ha_n = 0
    n = len(state.gateways())
    return {
        "version": __version__,
        "install_type": kind,
        "home_assistant": ha_version,
        "platform": {"os": ha_os or f"{platform.system()} {platform.release()}",
                     "arch": platform.machine(), "python": platform.python_version()},
        "integrations": {
            "local": {"on": n > 0, "gateways": n},
            "cloud": {"signed_in": configured and cloud_state == "valid",
                      "state": cloud_state},
            "modbus": {"on": modbus_on},
            "mqtt": {"on": bool(getattr(settings, "mqtt_enabled", False))},
            "ha_instances": ha_n,
        },
        "libraries": libraries(),
    }
