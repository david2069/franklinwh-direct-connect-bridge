"""Weather + solar-production forecast from Open-Meteo (free, no API key).

Fetches current weather + a 2-day hourly forecast, and scales the tilted-plane
irradiance (GTI) to the user's PV array (kWp, tilt, azimuth) to estimate hourly kW
and daily kWh. Results are cached (~15 min) so polling/sensors are cheap. Everything
is best-effort — a network hiccup returns the last cache or an empty forecast, never
an exception that breaks a page.
"""
from __future__ import annotations

import json
import logging
import time
import urllib.parse
import urllib.request

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
    params = {
        "latitude": lat, "longitude": lon, "timezone": "auto", "forecast_days": 2,
        "current": "temperature_2m,weather_code",
        "hourly": "temperature_2m,global_tilted_irradiance",
        "tilt": tilt, "azimuth": azimuth,
    }
    url = OPEN_METEO + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "franklinwh-direct-connect-bridge"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
        return json.loads(r.read())


def _compute(raw: dict, kwp: float) -> dict:
    cur = raw.get("current", {}) or {}
    code = cur.get("weather_code")
    hourly = raw.get("hourly", {}) or {}
    times = hourly.get("time", []) or []
    gti = hourly.get("global_tilted_irradiance", []) or []
    temps = hourly.get("temperature_2m", []) or []

    hours = []
    for i, t in enumerate(times):
        g = gti[i] if i < len(gti) and gti[i] is not None else 0
        # GTI (W/m²) at STC 1000 W/m² -> kWp array output, derated.
        kw = round(g / 1000.0 * kwp * PV_EFFICIENCY, 3)
        hours.append({"time": t, "kw": kw,
                      "temp_c": temps[i] if i < len(temps) else None})

    # Daily totals (hourly kW summed over 1h steps = kWh).
    by_day: dict = {}
    for h in hours:
        by_day.setdefault(h["time"][:10], []).append(h)
    days = []
    for d in sorted(by_day):
        hs = by_day[d]
        peak = max(hs, key=lambda x: x["kw"])
        days.append({"date": d, "total_kwh": round(sum(x["kw"] for x in hs), 1),
                     "peak_kw": peak["kw"], "peak_time": peak["time"][11:16]})

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
    }


def forecast(lat: float, lon: float, *, kwp: float = 5.0, tilt: float = 20.0,
             azimuth: float = 0.0, force: bool = False) -> dict:
    """Weather + PV forecast for a site. Cached ~15 min; returns the last good
    result (or an empty stub) on a fetch error."""
    key = f"{lat},{lon},{tilt},{azimuth},{kwp}"
    now = time.time()
    if not force and key in _cache and now - _cache[key][0] < CACHE_S:
        return _cache[key][1]
    try:
        out = _compute(_fetch(lat, lon, tilt, azimuth), kwp)
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
