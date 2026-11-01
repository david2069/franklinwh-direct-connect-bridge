"""The System view payload (#428): every gateway, from the poller's cache, for the shared
franklinwh-system-view overlay.

No device I/O: it reads ``last_summary`` only, so opening the view never sends anything to
an aGate. Anything the summary doesn't carry is left out rather than guessed; the overlay
draws only what is here. Signs follow the summary: ``grid_w`` > 0 imports, ``battery_w`` > 0
discharges.
"""
from __future__ import annotations

from typing import Any

from . import state

W = 50   # below this, solar or generator power counts as none (meter noise)


def _n(v: Any) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _reserve(summ: dict) -> float | None:
    for m in (summ.get("mode") or {}).get("modes") or []:
        if m.get("active"):
            return _n(m.get("reserved_soc"))
    return None


def _count(summ: dict) -> int | None:
    c = (summ.get("battery") or {}).get("count")
    if isinstance(c, int) and c > 0:
        return c
    sn = (summ.get("firmware") or {}).get("FHP_SN")
    return len(sn) if isinstance(sn, list) and sn else None


def gateway_payload(gw) -> dict:
    summ = gw.last_summary or {}
    power = summ.get("power") or {}
    ok = bool(summ.get("ok"))
    name = gw.label or gw.id
    if not ok:
        return {"id": gw.id, "name": name, "kind": "agate", "online": False,
                "mode": None, "inverter": None,
                "grid": {"state": "unknown", "power_w": None}, "home": {"power_w": None},
                "battery": {"soc_pct": None, "power_w": None, "count": _count(summ)},
                "solar": [], "circuits": []}
    off_grid = bool(power.get("off_grid")) or power.get("grid_present") is False
    grid = {"state": "outage" if off_grid else "connected", "power_w": _n(power.get("grid_w")),
            "voltage_v": _n(power.get("grid_voltage_v")), "freq_hz": _n(power.get("grid_freq_hz"))}
    soc = _n(power.get("soc"))
    if soc is not None:
        soc = max(0.0, min(100.0, soc))
    solar_w = _n(power.get("solar_w"))
    today = (summ.get("energy_today") or {}).get("solar")
    # Producing now, or produced today. A site that has never reported solar shows none.
    has_solar = (solar_w or 0) >= W or (_n(today) or 0) > 0
    gen_w = _n(power.get("generator_w"))
    has_gen = (gen_w or 0) >= W or (_n(power.get("kwh_gen")) or 0) > 0
    circuits = [{"id": int(k) if str(k).isdigit() else k, "name": f"Circuit {k}", "on": bool(v)}
                for k, v in sorted((summ.get("circuits_on") or {}).items())]
    return {
        "id": gw.id, "name": name, "kind": "agate", "online": True,
        "mode": power.get("mode"), "inverter": power.get("run_status_desc"),
        "reserve_pct": _reserve(summ),
        "grid": grid,
        "home": {"power_w": _n(power.get("load_w"))},
        "battery": {"soc_pct": soc, "power_w": _n(power.get("battery_w")), "count": _count(summ)},
        "solar": [{"id": "solar", "where": "agate", "power_w": solar_w}] if has_solar else [],
        "circuits": circuits,
        "generator": {"power_w": gen_w} if has_gen else None,
    }


def payload() -> dict:
    """The whole site: one entry per registered gateway, the active one first."""
    gws = state.gateways()
    active = state.default_gateway()
    gws = sorted(gws, key=lambda g: active is None or g.id != active.id)
    return {"version": 1, "site": {"name": "FranklinWH"},
            "gateways": [gateway_payload(g) for g in gws]}
