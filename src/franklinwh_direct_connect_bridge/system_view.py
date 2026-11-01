"""The System view payload (#428): every gateway, from the poller's cache, for the shared
franklinwh-system-view overlay.

No device I/O: it reads ``last_summary`` only, so opening the view never sends anything to
an aGate. The weather comes from the solar page's Open-Meteo forecast (refreshed in the
background when stale, never while a request waits), and the user's Customise diagram
answers from ``system_view.json`` in DATA_DIR. Anything the summary doesn't carry is left out rather than guessed; the overlay
draws only what is here. Signs follow the summary: ``grid_w`` > 0 imports, ``battery_w`` > 0
discharges.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

from . import environment, state

log = logging.getLogger(__name__)

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
    legs = [v for v in (power.get("grid_leg_v") or []) if _n(v) is not None]
    if legs:
        grid["legs_v"] = legs
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


# ── the site: its name from the location, and the weather now ─────────────────

_refreshing = threading.Lock()


def _forecast(cfg) -> dict | None:
    """The solar page's cached forecast for this location; a stale or missing one is
    refreshed in the background, so a request never waits on Open-Meteo."""
    from . import solar_forecast
    if cfg is None or cfg.pv_latitude is None or cfg.pv_longitude is None:
        return None
    key = f"{cfg.pv_latitude},{cfg.pv_longitude},{cfg.pv_tilt},{cfg.pv_azimuth},{cfg.pv_kwp}"
    hit = solar_forecast._cache.get(key)
    if (hit is None or time.time() - hit[0] >= solar_forecast.CACHE_S) and _refreshing.acquire(blocking=False):
        def run():
            try:
                solar_forecast.forecast(cfg.pv_latitude, cfg.pv_longitude, kwp=cfg.pv_kwp,
                                        tilt=cfg.pv_tilt, azimuth=cfg.pv_azimuth)
            finally:
                _refreshing.release()
        threading.Thread(target=run, name="system-view-weather", daemon=True).start()
    return hit[1] if hit else None


def place(tz: Any) -> str | None:
    """A timezone's place: ``Australia/Sydney`` → ``Sydney``."""
    if not isinstance(tz, str) or "/" not in tz:
        return None
    return tz.rsplit("/", 1)[1].replace("_", " ")


def site(cfg) -> dict:
    fc = _forecast(cfg)
    out: dict = {}
    if fc:
        name = place(fc.get("timezone"))
        if name:
            out["name"], out["timezone"] = name, fc["timezone"]
        cur = fc.get("current") or {}
        if isinstance(cur.get("code"), int):
            out["weather"] = {"code": cur["code"], "condition": cur.get("condition"),
                              "temp_c": _n(cur.get("temp_c"))}
    return out


# ── Customise diagram answers ────────────────────────────────────────────────

def saved_path() -> Path:
    return Path(environment.DATA_DIR) / "system_view.json"


def load_saved() -> dict:
    """The user's answers; a missing or unreadable file is no answers."""
    try:
        data = json.loads(saved_path().read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save(values: dict) -> None:
    p = saved_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(values, indent=1))
    tmp.replace(p)


def raw_payload(cfg=None) -> dict:
    """The site from readings alone, before the user's answers."""
    gws = state.gateways()
    active = state.default_gateway()
    gws = sorted(gws, key=lambda g: active is None or g.id != active.id)
    return {"version": 1, "site": site(cfg), "gateways": [gateway_payload(g) for g in gws]}


INTRO = ("Where no reading tells the bridge how your site is built, tell it here. Empty or "
         "Automatic uses the readings. Saved in the bridge, so every browser shows the same diagram.")


def payload(cfg=None) -> dict:
    """The whole site with the user's answers applied, and the Customise diagram form."""
    import franklinwh_system_view as sv
    raw, saved = raw_payload(cfg), load_saved()
    out = sv.customise.apply(raw, saved)
    out["customise"] = {"endpoint": "api/system/customise", "intro": INTRO,
                        "fields": sv.customise.fields(raw, saved)}
    return out
