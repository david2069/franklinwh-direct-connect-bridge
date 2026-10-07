"""Per-gateway System Setup / install profile (FEAT-SYSTEM-SETUP).

Install characteristics a schedule may want as context — solar type/size, generator,
grid-forming, whole-home backup, load shedding, battery label. DERIVED from the local
API where possible (device as reference), with a per-gateway user override that WINS
— the pattern used across this bridge. Exposed as ``system.*`` condition sensors.

Derivation (cached ~1 h — install config is static):
  solar_pv (1903)  → solar_type (ac / remote / none) + solar_kwp (PVx RatedPower ×100 W)
  generator (1901) → generator_input (genEn)
Others (grid_forming, whole_home_backup, load_shedding, non_backup_loads, battery_label)
default sensibly and are user-set (1701 is unreliable for them on current firmware).
"""
from __future__ import annotations

import json
import time as _time
from typing import Any

_KEY_PREFIX = "system_setup:"
_DERIVE_TTL = 3600.0
_derive_cache: dict[str, tuple] = {}   # host -> (expires_monotonic, derived dict)

#: field -> (default, derived?) — derived fields show a "derived" hint in the UI.
_FIELDS: dict[str, dict] = {
    "solar_type":        {"default": "none",         "derived": True,  "kind": "enum",
                          "options": ["none", "ac", "dc", "remote"]},
    "solar_kwp":         {"default": 0.0,            "derived": True,  "kind": "number"},
    "generator_input":   {"default": False,          "derived": True,  "kind": "bool"},
    "grid_forming":      {"default": True,           "derived": False, "kind": "bool"},
    "whole_home_backup": {"default": True,           "derived": False, "kind": "bool"},
    "load_shedding":     {"default": False,          "derived": True,  "kind": "bool"},
    "non_backup_loads":  {"default": False,          "derived": False, "kind": "bool"},
    "battery_label":     {"default": "FranklinWH",   "derived": False, "kind": "text"},
}


def _num(v: Any, d: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def spec() -> dict:
    return {k: {"default": v["default"], "derived": v["derived"], "kind": v["kind"],
                **({"options": v["options"]} if "options" in v else {})}
            for k, v in _FIELDS.items()}


def _derive(settings, host) -> dict:
    """Best-effort derive from the aGate (solar 1903 + generator 1901), cached ~1 h.
    Returns {} when there's no host or the reads fail (stale cache re-used if present)."""
    if not host:
        return {}
    now = _time.monotonic()
    hit = _derive_cache.get(host)
    if hit and hit[0] > now:
        return hit[1]
    out: dict[str, Any] = {}
    try:
        from .client import _client
        with _client(settings, host) as c:
            manifest = c.login()
            try:
                sp = c.solar_pv() or {}
                kwp = round((_num(sp.get("PV1RatedPower")) + _num(sp.get("PV2RatedPower"))) * 100 / 1000.0, 2)
                if kwp <= 0 and _num(sp.get("solarRatedPower")) > 0:
                    kwp = round(_num(sp.get("solarRatedPower")) / 1000.0, 2)
                out["solar_kwp"] = kwp
                if sp.get("installPV1port") or sp.get("installPV2port"):
                    out["solar_type"] = "ac"
                elif sp.get("remoteSolarEn"):
                    out["solar_type"] = "remote"
                elif kwp > 0:
                    out["solar_type"] = "ac"
                else:
                    out["solar_type"] = "none"
            except Exception:                                   # noqa: BLE001
                pass
            try:
                gen = c.generator() or {}
                out["generator_input"] = bool(gen.get("genEn"))
            except Exception:                                   # noqa: BLE001
                pass
            try:
                # Load shedding is a Smart-Circuits capability (LOCAL-only — Modbus has no
                # smart-circuit registers). Present when smart circuits are detected.
                from . import circuits as _circuits, devicedb
                cfg = c.smart_circuits() or {}
                model = devicedb.describe(manifest)
                view = _circuits.build(cfg, None, expected=model.get("expected_circuits"))
                out["load_shedding"] = bool(view.get("installed"))
            except Exception:                                   # noqa: BLE001
                pass
    except Exception:                                           # noqa: BLE001
        return (hit[1] if hit else {})                          # keep stale rather than nothing
    _derive_cache[host] = (now + _DERIVE_TTL, out)
    return out


def _overrides(store, gateway_id: str) -> dict:
    if store is None:
        return {}
    try:
        raw = store.get_config(_KEY_PREFIX + (gateway_id or "default"))
        return json.loads(raw) if raw else {}
    except Exception:                                           # noqa: BLE001
        return {}


def values(store, settings=None, gateway_id=None, host=None) -> dict:
    """Resolved System Setup: default → derived → user override (override wins).
    Also reports, per field, whether the value is user-set (`_overridden`)."""
    derived = _derive(settings, host) if settings is not None else {}
    ov = _overrides(store, gateway_id or "default")
    out: dict[str, Any] = {}
    for k, spc in _FIELDS.items():
        if k in ov and ov[k] is not None:
            out[k] = ov[k]
        elif k in derived and derived[k] is not None:
            out[k] = derived[k]
        else:
            out[k] = spc["default"]
    out["_derived"] = {k: derived[k] for k in _FIELDS if k in derived}
    out["_overridden"] = {k: (k in ov and ov[k] is not None) for k in _FIELDS}
    return out


def update(store, gateway_id, updates: dict) -> dict:
    """Persist user overrides for the known fields; clearing (null) reverts to derived."""
    if store is None:
        return {}
    ov = _overrides(store, gateway_id or "default")
    for k, v in (updates or {}).items():
        if k not in _FIELDS:
            continue
        if v is None:
            ov.pop(k, None)
        elif _FIELDS[k]["kind"] == "bool":
            ov[k] = bool(v)
        elif _FIELDS[k]["kind"] == "number":
            ov[k] = _num(v)
        else:
            ov[k] = v
    store.set_config(_KEY_PREFIX + (gateway_id or "default"), json.dumps(ov))
    return ov


def snapshot(store, settings=None, gateway_id=None, host=None) -> dict:
    """system.* sensor values for the gate snapshot."""
    v = values(store, settings, gateway_id, host)
    return {f"system.{k}": v[k] for k in _FIELDS}
