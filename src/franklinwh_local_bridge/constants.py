"""User-defined automation constants — values automations (and the schedule
builder) use but that either can't be read from the aGate or express user intent:

  * SoC parameters: min-discharge / max-charge / demand-charge SoC (percent).
  * default_operating_mode: the mode the user considers "normal" for this gate —
    used for comparison sensors (e.g. "current mode != default") and, later, for
    an opt-in restore-on-schedule-exit. Storing it does NOT write to the aGate.

Persisted in the metrics store's ``app_config`` KV under a single JSON key and
surfaced to the scheduler as ``const.*`` condition sensors (Modbus-bridge parity).
"""
from __future__ import annotations

import json

_KEY = "automation_constants"

#: numeric SoC constants — name -> (default, min, max), percent.
_SPEC: dict[str, tuple[float, float, float]] = {
    "min_discharge_soc": (20.0, 0.0, 100.0),
    "max_charge_soc": (100.0, 0.0, 100.0),
    "demand_charge_min_soc": (30.0, 0.0, 100.0),
    # Battery usable capacity (kWh). The local API exposes no capacity register, so
    # the user sets it here; 0 = unset (the derived energy/ETA sensors then read None).
    "battery_capacity_kwh": (0.0, 0.0, 1000.0),
    # Max continuous battery power (kW) — FALLBACK for the "at max rate" ETA when Modbus
    # SunSpec 702 can't be read. Modbus (when enabled) overrides this. Default 5 kW (aPower X).
    "battery_max_power_kw": (5.0, 0.0, 100.0),
}

#: operating-mode aliases (local set_mode alias -> friendly label + cloud workMode).
#: Availability is per-install; the UI derives the *offered* set from the aGate's
#: mode_list (/api/cloud/reserves). Emergency Backup is always present; Self-
#: Consumption needs solar configured; Time-of-Use needs the installer's TOU setup.
_MODES: dict[str, dict] = {
    "self":   {"label": "Self-Consumption", "work_mode": 2},
    "tou":    {"label": "Time-of-Use",      "work_mode": 1},
    "backup": {"label": "Emergency Backup", "work_mode": 3},
}
_MODE_KEY = "default_operating_mode"
_MODE_DEFAULT = "self"

#: cloud workMode int -> local alias (for deriving options from /api/cloud/reserves).
WORKMODE_ALIAS = {v["work_mode"]: k for k, v in _MODES.items()}


def spec() -> dict:
    """Field spec for the settings form: SoC bounds + the mode option catalogue."""
    out: dict = {k: {"default": d, "min": lo, "max": hi} for k, (d, lo, hi) in _SPEC.items()}
    out[_MODE_KEY] = {
        "default": _MODE_DEFAULT,
        "options": [{"value": k, "label": v["label"], "work_mode": v["work_mode"]}
                    for k, v in _MODES.items()],
    }
    return out


def _defaults() -> dict:
    out: dict = {k: v[0] for k, v in _SPEC.items()}
    out[_MODE_KEY] = _MODE_DEFAULT
    return out


def values(store) -> dict:
    """Current constants — defaults merged with any stored overrides."""
    out = _defaults()
    if store is None:
        return out
    try:
        raw = store.get_config(_KEY)
        if raw:
            stored = json.loads(raw)
            for k in _SPEC:
                if k in stored and stored[k] is not None:
                    out[k] = float(stored[k])
            m = stored.get(_MODE_KEY)
            if isinstance(m, str) and m in _MODES:
                out[_MODE_KEY] = m
    except Exception:                                           # noqa: BLE001
        pass
    return out


def update(store, updates: dict) -> dict:
    """Apply + persist known keys. SoC clamped to [min,max]; mode validated against
    the known aliases (unknown mode ignored). Non-numeric SoC raises ValueError."""
    vals = values(store)
    for k, v in (updates or {}).items():
        if k in _SPEC and v is not None:
            fv = float(v)                                       # raises on non-numeric
            lo, hi = _SPEC[k][1], _SPEC[k][2]
            vals[k] = max(lo, min(hi, fv))
        elif k == _MODE_KEY and isinstance(v, str) and v in _MODES:
            vals[_MODE_KEY] = v
    if store is not None:
        store.set_config(_KEY, json.dumps(vals))
    return vals


def snapshot(store) -> dict:
    """const.* sensor values for the scheduler snapshot."""
    v = values(store)
    out = {f"const.{k}": v[k] for k in _SPEC}
    out["const.default_operating_mode"] = v[_MODE_KEY]
    return out
