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

from .devicedb import APOWER_SPECS

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
    # #496: the aPower family, read from PE_HW_VER via the catalogue; asked only when unknown.
    "apower_model":      {"default": "",             "derived": True,  "kind": "enum",
                          "options": ["", *APOWER_SPECS]},
    "v2l":               {"default": False,          "derived": True,  "kind": "bool"},
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


def _solar_source(sp: dict, kind: str, kwp: float) -> str:
    """Where the solar answer came from, in words (#496)."""
    from .solar import _kw
    if kind == "ac":
        ports = [f"PV port {n} ({_kw(sp.get(f'PV{n}RatedPower')) or 0:g} kW)"
                 for n in (1, 2) if sp.get(f"installPV{n}port")]
        return ("Read from the gateway's PV settings: " + ", ".join(ports) if ports
                else f"Read from the gateway's PV settings: rated {kwp:g} kW")
    if kind == "remote":
        return f"Read from the gateway's PV settings: remote solar on, rated {kwp:g} kW"
    return "The gateway's PV settings show no solar"


def _generator_source(gen: dict) -> str:
    from . import generator as _gen
    head = "Read from the gateway's generator settings: "
    bits = [b for b in ((gen.get("genModel") or "").strip(),
                        f"{_num(gen.get('genRatedPower')) / 1000:g} kW" if gen.get("genRatedPower") else "")
            if b]
    if bits:
        return head + ", ".join((["turned on"] if _gen.enabled(gen) else []) + bits)
    if _gen.enabled(gen):
        return head + "turned on (no model or rating reported)"
    return head + "not turned on, and no model or rating"


def reported_solar_kwp(host) -> float | None:
    """The solar size this gateway last reported (1903), from the derive cache: no read,
    so a tick never waits on the gateway (#583). None until it has been read."""
    hit = _derive_cache.get(host) if host else None
    kwp = (hit[1] if hit else {}).get("solar_kwp")
    return float(kwp) if isinstance(kwp, (int, float)) and kwp > 0 else None


def _derive(settings, host) -> dict:
    """Best-effort derive from the aGate (solar 1903 + generator 1901), cached ~1 h.
    Returns {} when there's no host or the reads fail (stale cache re-used if present).
    ``_sources`` says, per item, where the value came from (#496)."""
    if not host:
        return {}
    now = _time.monotonic()
    hit = _derive_cache.get(host)
    if hit and hit[0] > now:
        return hit[1]
    out: dict[str, Any] = {}
    sources: dict[str, str] = {}
    try:
        from .client import _client
        with _client(settings, host) as c:
            manifest = c.login()
            try:
                from . import devicedb
                units = devicedb.apowers(manifest)
                if units:
                    out["_apower_models"] = [u["model"] if u else None for u in units]
                    fams = {u["family"] if u else None for u in units}
                    if len(fams) == 1 and None not in fams:
                        out["apower_model"] = fams.pop()
                    codes = ", ".join(str(c) for c in manifest.get("PE_HW_VER"))
                    sources["apower"] = ("Read from the gateway's list of aPowers "
                                         f"(model code {codes})")
            except Exception:                                   # noqa: BLE001
                pass
            try:
                sp = c.solar_pv() or {}
                kwp = round((_num(sp.get("PV1RatedPower")) + _num(sp.get("PV2RatedPower"))) * 100 / 1000.0, 2)
                if kwp <= 0 and _num(sp.get("solarRatedPower")) > 0:
                    # 100 W steps, as the Solar tab reads it (solar._kw) — #496.
                    kwp = round(_num(sp.get("solarRatedPower")) * 100 / 1000.0, 2)
                out["solar_kwp"] = kwp
                if sp.get("installPV1port") or sp.get("installPV2port"):
                    out["solar_type"] = "ac"
                elif sp.get("remoteSolarEn"):
                    out["solar_type"] = "remote"
                elif kwp > 0:
                    out["solar_type"] = "ac"
                else:
                    out["solar_type"] = "none"
                sources["solar"] = _solar_source(sp, out["solar_type"], kwp)
            except Exception:                                   # noqa: BLE001
                pass
            try:
                gen = c.generator() or {}
                # Installed, like Smart Circuits and V2L (owner, 2026-11-05): turned on,
                # or a model, rating or run state reported.
                from . import generator as _gen
                out["generator_input"] = _gen.installed(gen)
                sources["generator_input"] = _generator_source(gen)
            except Exception:                                   # noqa: BLE001
                pass
            try:
                # Load shedding is a Smart-Circuits capability (LOCAL-only — Modbus has no
                # smart-circuit registers). Present when smart circuits are detected.
                from . import circuits as _circuits, devicedb
                cfg = c.smart_circuits() or {}
                try:
                    meter = c.smart_circuit_meter() or {}
                except Exception:                               # noqa: BLE001
                    meter = {}
                model = devicedb.describe(manifest)
                view = _circuits.build(cfg, None, expected=model.get("expected_circuits"))
                out["load_shedding"] = bool(view.get("installed"))
                n = view.get("count") or 0
                out["_circuit_count"] = n
                sources["load_shedding"] = (f"Read from the gateway's Smart Circuits: {n} found"
                                            if n else "The gateway reports no Smart Circuits")
                car = _circuits.carsw(meter, cfg)
                used = sum(v for v in (car.get("export_lifetime_kwh"), car.get("import_lifetime_kwh"))
                           if isinstance(v, (int, float)))
                # Installed when turned on, or when it has ever carried energy (#496).
                out["v2l"] = bool(car.get("enabled")) or used > 0
                if used > 0:
                    sources["v2l"] = (f"Read from the gateway's V2L meter: {used:g} kWh through "
                                      "the car switch")
                else:
                    sources["v2l"] = ("V2L (car switch) is turned on in the gateway's Smart "
                                      "Circuits settings" if out["v2l"] else
                                      "V2L (car switch) is not turned on in the gateway's "
                                      "settings, and its meter shows no energy")
            except Exception:                                   # noqa: BLE001
                pass
    except Exception:                                           # noqa: BLE001
        return (hit[1] if hit else {})                          # keep stale rather than nothing
    out["_sources"] = sources
    _derive_cache[host] = (now + _DERIVE_TTL, out)
    return out


def _gw_key(gateway_id) -> str:
    """Overrides are kept under the gateway's id (#379); there is no "default" key."""
    if not gateway_id:
        raise ValueError("System Setup needs a gateway")
    return gateway_id


def _overrides(store, gateway_id: str) -> dict:
    if store is None:
        return {}
    try:
        raw = store.get_config(_KEY_PREFIX + _gw_key(gateway_id))
        return json.loads(raw) if raw else {}
    except Exception:                                           # noqa: BLE001
        return {}


def values(store, settings=None, gateway_id=None, host=None) -> dict:
    """Resolved System Setup: default → derived → user override (override wins).
    Also reports, per field, whether the value is user-set (`_overridden`)."""
    derived = _derive(settings, host) if settings is not None else {}
    ov = _overrides(store, gateway_id)
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
    out["_sources"] = dict(derived.get("_sources") or {})
    out["_circuit_count"] = derived.get("_circuit_count")
    out["_apower_models"] = derived.get("_apower_models")
    out["_confirmed"] = dict(ov.get(_CONFIRMED) or {})
    return out


#: Inside the overrides blob: what the user confirmed, as {item: the value they saw}.
#: Kept apart from the overrides, so confirming never stops a value being re-read (#496).
_CONFIRMED = "_confirmed"


def confirm(store, gateway_id, keys, shown: dict) -> dict:
    """Record that the user confirmed these items as shown (``shown`` = item → value text)."""
    if store is None:
        return {}
    ov = _overrides(store, gateway_id)
    done = dict(ov.get(_CONFIRMED) or {})
    for k in keys or []:
        if k in shown:
            done[k] = shown[k]
    ov[_CONFIRMED] = done
    store.set_config(_KEY_PREFIX + _gw_key(gateway_id), json.dumps(ov))
    return done


def update(store, gateway_id, updates: dict) -> dict:
    """Persist user overrides for the known fields; clearing (null) reverts to derived."""
    if store is None:
        return {}
    ov = _overrides(store, gateway_id)
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
    store.set_config(_KEY_PREFIX + _gw_key(gateway_id), json.dumps(ov))
    return ov


def snapshot(store, settings=None, gateway_id=None, host=None) -> dict:
    """system.* sensor values for the gate snapshot."""
    v = values(store, settings, gateway_id, host)
    return {f"system.{k}": v[k] for k in _FIELDS}
