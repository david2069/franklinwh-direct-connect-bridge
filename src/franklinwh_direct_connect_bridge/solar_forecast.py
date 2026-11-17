"""Weather + solar-production forecast from Open-Meteo (free, no API key).

Fetches current weather + a 2-day hourly forecast, and scales the tilted-plane
irradiance (GTI) to the user's PV array (kWp, tilt, azimuth) to estimate hourly kW
and daily kWh. Results are cached (~15 min) so polling/sensors are cheap. Everything
is best-effort — a network hiccup returns the last cache or an empty forecast, never
an exception that breaks a page.

The maths come from hems, the shared engine (#713, #612): the request and parsing from
``hems.adapters.open_meteo``, the kW from ``hems.forecast.solar`` (with the cell-temperature
loss), and a self-calibration against the solar the site's gateways measured.
"""
from __future__ import annotations

import json
import logging
import time

from hems import forecast as hforecast
from hems.adapters import open_meteo

log = logging.getLogger(__name__)

OPEN_METEO = "https://api.open-meteo.com/v1/forecast"
CACHE_S = 900          # 15 minutes
PV_EFFICIENCY = 0.85   # inverter + wiring + soiling derate (GTI -> AC)
TIMEOUT_S = 15

# WMO weather codes -> short label (Open-Meteo `weather_code`).
WEATHER_CODES = {
    0: "Clear", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Rime fog", 51: "Light drizzle", 53: "Drizzle", 55: "Dense drizzle",
    56: "Freezing drizzle", 57: "Freezing drizzle", 61: "Light rain", 63: "Rain",
    65: "Heavy rain", 66: "Freezing rain", 67: "Freezing rain", 71: "Light snow",
    73: "Snow", 75: "Heavy snow", 77: "Snow grains", 80: "Rain showers",
    81: "Rain showers", 82: "Violent showers", 85: "Snow showers", 86: "Snow showers",
    95: "Thunderstorm", 96: "Thunderstorm, hail", 99: "Thunderstorm, hail",
}

_cache: dict = {}   # key -> (ts, data)


def _fetch(lat: float, lon: float, tilt: float, azimuth: float) -> dict:
    # hems's forecast request, plus the current weather; timezone=auto keeps the hourly
    # times location-local, as the card, the sensors and solar_fill read them.
    params = {**open_meteo.forecast_params(lat, lon, tilt=tilt, azimuth=azimuth),
              "timezone": "auto", "current": "temperature_2m,weather_code"}
    return open_meteo.fetch(open_meteo.FORECAST_URL, params, timeout=TIMEOUT_S,
                            user_agent="franklinwh-direct-connect-bridge")


def _compute(raw: dict, kwp: float, calibration: float = 1.0) -> dict:
    cur = raw.get("current", {}) or {}
    code = cur.get("weather_code")
    times = (raw.get("hourly", {}) or {}).get("time", []) or []
    rows = open_meteo.parse_hourly(raw)
    # GTI (W/m²) at STC 1000 W/m² -> kWp array output, derated, less the cell-temperature
    # loss; once with the calibration and once without, for the calibration's own record.
    pv = hforecast.solar(rows, kwp, derate=PV_EFFICIENCY, calibration=calibration)
    pv_raw = (hforecast.solar(rows, kwp, derate=PV_EFFICIENCY) if calibration != 1.0 else pv)

    hours = []
    for i, t in enumerate(times):
        hours.append({"time": t, "kw": pv[i]["kw"], "temp_c": rows[i]["temp_c"],
                      "_raw": pv_raw[i]["kw"]})

    # Daily totals (hourly kW summed over 1h steps = kWh).
    by_day: dict = {}
    for h in hours:
        by_day.setdefault(h["time"][:10], []).append(h)
    days = []
    for d in sorted(by_day):
        hs = by_day[d]
        peak = max(hs, key=lambda x: x["kw"])
        days.append({"date": d, "total_kwh": round(sum(x["kw"] for x in hs), 1),
                     "raw_total_kwh": round(sum(x["_raw"] for x in hs), 1),
                     "peak_kw": peak["kw"], "peak_time": peak["time"][11:16]})
    for h in hours:
        del h["_raw"]

    return {
        "current": {"temp_c": cur.get("temperature_2m"), "code": code,
                    "condition": WEATHER_CODES.get(code, "—")},
        "days": days, "hourly": hours,
        # Open-Meteo (timezone=auto) returns LOCATION-LOCAL hourly times; carry the
        # location's UTC offset so callers can align "now" to the same clock rather
        # than to UTC or the container's TZ.
        "utc_offset_seconds": raw.get("utc_offset_seconds"),
        "timezone": raw.get("timezone"),
        "generated_at": int(time.time()),
        "calibration": calibration,
    }


def site_key(lat, lon, tilt, azimuth, kwp) -> str:
    """The forecast's cache key, and its calibration's: a changed array starts afresh."""
    return f"{lat},{lon},{tilt},{azimuth},{kwp}"


def forecast(lat: float, lon: float, *, kwp: float = 5.0, tilt: float = 20.0,
             azimuth: float = 0.0, force: bool = False, store=None) -> dict:
    """Weather + PV forecast for a site. Cached ~15 min; returns the last good
    result (or an empty stub) on a fetch error. With ``store``, scaled by the site's
    calibration (1.0 until there are enough measured days)."""
    key = site_key(lat, lon, tilt, azimuth, kwp)
    now = time.time()
    if not force and key in _cache and now - _cache[key][0] < CACHE_S:
        return _cache[key][1]
    try:
        out = _compute(_fetch(lat, lon, tilt, azimuth), kwp, calibration(store, key))
        _cache[key] = (now, out)
        return out
    except Exception as e:                                       # noqa: BLE001
        log.warning("solar forecast fetch failed: %s", e)
        if key in _cache:
            return {**_cache[key][1], "stale": True}
        return {"current": {"temp_c": None, "condition": "—", "code": None},
                "days": [], "hourly": [], "error": str(e)}


def sensors(fc: dict) -> dict:
    """Flatten a forecast into the scheduler sensor namespace (weather.* /
    solar_forecast.*). Missing data -> None (fails a gate closed, never fires)."""
    cur = (fc or {}).get("current", {}) or {}
    days = (fc or {}).get("days", []) or []
    hourly = (fc or {}).get("hourly", []) or []
    today = days[0] if days else {}
    tomorrow = days[1] if len(days) > 1 else {}
    # Remaining production today = sum of hourly kW from now on for today's date.
    # Compute "now" in the LOCATION's local time (Open-Meteo hourly times are local),
    # not the container's TZ — otherwise a UTC container mis-sums the remaining hours.
    import datetime as _dt
    _off = (fc or {}).get("utc_offset_seconds") or 0
    now = (_dt.datetime.utcnow() + _dt.timedelta(seconds=_off)).strftime("%Y-%m-%dT%H:%M")
    today_date = today.get("date")
    remaining = None
    if today_date:
        remaining = round(sum(h["kw"] for h in hourly
                              if h["time"][:10] == today_date and h["time"] >= now), 1)
    return {
        "weather.temp_c": cur.get("temp_c"),
        "weather.condition": cur.get("condition"),
        "weather.code": cur.get("code"),
        "solar_forecast.today_kwh": today.get("total_kwh"),
        "solar_forecast.today_peak_kw": today.get("peak_kw"),
        "solar_forecast.remaining_kwh": remaining,
        "solar_forecast.tomorrow_kwh": tomorrow.get("total_kwh"),
    }


# ── Calibration (#713) ─────────────────────────────────────────────────────────────
#: app_config keys: hems's calibration state, and the day being measured, per site key.
CAL_KEY = "solar_calibration:{key}"
DAY_KEY = "solar_calibration_day:{key}"


def _load(store, k: str):
    try:
        v = store.get_config(k) if store is not None else None
        return json.loads(v) if v else None
    except Exception:                                            # noqa: BLE001
        return None


def calibration(store, key: str) -> float:
    """Measured ÷ forecast over the site's recent days (hems), 1.0 without a store or
    enough days. Never raises."""
    state = _load(store, CAL_KEY.format(key=key))
    return hforecast.calibration_factor(state) if state else 1.0


def observe(store, key: str, *, day: str, gateway_id: str, predicted_kwh, measured_kwh) -> None:
    """One gateway's solar so far on ``day`` and the uncalibrated forecast for it. The
    highest reading per gateway counts (the aGate's counter only rises in a day), and a
    site's gateways add up. When the day changes, the finished day goes into hems's
    calibration. Never raises."""
    if store is None:
        return
    try:
        cur = _load(store, DAY_KEY.format(key=key)) or {}
        if cur.get("day") and cur["day"] != day:
            state = _load(store, CAL_KEY.format(key=key)) or hforecast.new_calibration()
            meas = sum((cur.get("meas") or {}).values()) if cur.get("meas") else None
            hforecast.add_solar_day(state, day=cur["day"], predicted_kwh=cur.get("pred"),
                                    measured_kwh=meas)
            store.set_config(CAL_KEY.format(key=key), json.dumps(state))
            cur = {}
        cur["day"] = day
        if predicted_kwh is not None:
            cur["pred"] = float(predicted_kwh)
        if measured_kwh is not None:
            m = cur.setdefault("meas", {})
            m[gateway_id] = max(float(measured_kwh), float(m.get(gateway_id) or 0))
        store.set_config(DAY_KEY.format(key=key), json.dumps(cur))
    except Exception as e:                                       # noqa: BLE001
        log.debug("solar calibration not recorded: %s", e)
