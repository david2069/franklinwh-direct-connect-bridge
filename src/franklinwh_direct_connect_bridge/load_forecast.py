"""Home-load forecast from hems (#713 step 3, #612 §4).

The model is ``hems.forecast.fit_load`` on this gateway's hourly home load (the stored polls)
and the site's hourly air temperature (Open-Meteo's archive, fetched at most once a day and
kept in ``app_config``). It is fitted once a site day and predicts the next 48 hours with the
solar forecast's temperatures. Home Assistant gets it as a ``Load Forecast`` sensor whose
``forecast`` attribute is HAEO's 30-minute series (``hems.forecast.haeo``). The weekly
battery report carries ``hems.forecast.backtest_load`` over the last 90 days.

Read-only: nothing here talks to an aGate. Every entry point is best-effort and never
raises; with too little history the cold start (or nothing) is what comes out.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from hems import forecast as hforecast
from hems.adapters import open_meteo

log = logging.getLogger(__name__)

#: Days of history the model learns from (hems keeps at most 365).
HISTORY_DAYS = 365
#: Hours ahead in the forecast.
HORIZON_H = 48
#: Days the weekly report's backtest walks over.
BACKTEST_DAYS = 90
#: app_config: the site's archive temperatures, ``{"day": fetched site day, "t": {hour: °C}}``.
TEMPS_KEY = "load_forecast_temps:{lat},{lon}"
#: The archive lags real time by a few days; ask for up to this many days back.
ARCHIVE_LAG_DAYS = 2

_models: dict[str, tuple[str, dict, int]] = {}  # gateway -> (site day, model, hour fitted)


def _zone(store) -> ZoneInfo:
    from . import setup_wizard
    try:
        name = setup_wizard.site_timezone(store)
        return ZoneInfo(name) if name else ZoneInfo("UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def metrics_key(gateway_id: str) -> str:
    """The gateway's tag on metrics rows: its serial, else its id (as the poller writes)."""
    from . import state
    gw = state.get_gateway(gateway_id)
    return (gw.serial if gw is not None and gw.serial else None) or gateway_id


def hourly_load(store, gateway_id: str, start: int, end: int) -> list[dict]:
    """``[{start, kwh}]`` per hour: the hour's mean home load (W) ÷ 1000."""
    rows = store.query(start, end, 3600, gateway=metrics_key(gateway_id))
    return [{"start": r["ts"], "kwh": round(r["load_w"] / 1000, 4)}
            for r in rows if r.get("load_w") is not None]


def archive_temps(store, loc: dict, tz: ZoneInfo, start: int, end: int, *,
                  fetch=None) -> dict[int, float]:
    """``{hour start: °C}`` for the site, from the archive. Fetched at most once a site day
    and kept; a failed fetch keeps what was there. Never raises."""
    if loc.get("latitude") is None or loc.get("longitude") is None:
        return {}
    key = TEMPS_KEY.format(lat=loc["latitude"], lon=loc["longitude"])
    try:
        cur = json.loads(store.get_config(key) or "{}")
    except Exception:                                            # noqa: BLE001
        cur = {}
    have = {int(k): v for k, v in (cur.get("t") or {}).items()}
    today = dt.datetime.fromtimestamp(end, tz).date()
    if cur.get("day") != today.isoformat():
        try:
            first = dt.datetime.fromtimestamp(start, tz).date()
            last = today - dt.timedelta(days=ARCHIVE_LAG_DAYS)
            params = open_meteo.archive_params(
                loc["latitude"], loc["longitude"], start=first.isoformat(),
                end=last.isoformat(), tilt=loc.get("pv_tilt") or 0,
                azimuth=loc.get("pv_azimuth") or 0)
            raw = (fetch or open_meteo.fetch)(open_meteo.ARCHIVE_URL, params,
                                              user_agent="franklinwh-direct-connect-bridge")
            for r in open_meteo.parse_hourly(raw):
                if r["temp_c"] is not None:
                    have[int(r["start"])] = r["temp_c"]
            have = {k: v for k, v in have.items() if k >= start}
            store.set_config(key, json.dumps({"day": today.isoformat(),
                                              "t": {str(k): v for k, v in have.items()}}))
        except Exception as e:                                   # noqa: BLE001
            log.debug("load forecast: archive temperatures not fetched: %s", e)
    return have


def history(store, gateway_id: str, loc: dict, tz: ZoneInfo, now: float,
            days: int = HISTORY_DAYS, *, fetch=None) -> list[dict]:
    """hems's history rows ``{start, kwh, temp_c}`` for the last ``days``."""
    start = int(now) - days * 86400
    temps = archive_temps(store, loc, tz, start, int(now), fetch=fetch)
    return [{**h, "temp_c": temps.get(h["start"])}
            for h in hourly_load(store, gateway_id, start, int(now))]


def _forecast_temps(fc: dict) -> dict[int, float]:
    """``{hour start: °C}`` from the solar forecast's location-local hours."""
    off = dt.timezone(dt.timedelta(seconds=int((fc or {}).get("utc_offset_seconds") or 0)))
    out = {}
    for h in (fc or {}).get("hourly") or []:
        try:
            t = dt.datetime.fromisoformat(h["time"]).replace(tzinfo=off)
        except (KeyError, TypeError, ValueError):
            continue
        if h.get("temp_c") is not None:
            out[int(t.timestamp())] = h["temp_c"]
    return out


def model(store, gateway_id: str, loc: dict, now: float, *, fetch=None) -> dict:
    """The gateway's load model, fitted once a site day; while it is still degraded (too
    little history for the model), once an hour, so a new install picks up its first days."""
    tz = _zone(store)
    local = dt.datetime.fromtimestamp(now, tz)
    hit = _models.get(gateway_id)
    if hit and hit[0] == local.date().isoformat() and not (
            hit[1].get("degraded") and hit[2] != local.hour):
        return hit[1]
    m = hforecast.fit_load(history(store, gateway_id, loc, tz, now, fetch=fetch), tz=tz)
    _models[gateway_id] = (local.date().isoformat(), m, local.hour)
    return m


def history_days(store, gateway_id: str, now: float, days: int = HISTORY_DAYS) -> int:
    """Site days with home load in the last ``days`` (what the forecast can learn from)."""
    tz = _zone(store)
    return len({dt.datetime.fromtimestamp(h["start"], tz).date()
                for h in hourly_load(store, gateway_id, int(now) - days * 86400, int(now))})


def predict(store, gateway_id: str, loc: dict, fc: dict | None, now: float, *,
            fetch=None, baseline_kwh: float | None = None) -> list[dict]:
    """``[{start, kwh, method}]`` for the next ``HORIZON_H`` hours from this hour. An hour
    with no history at all is ``baseline_kwh`` (the always-on load) when given."""
    m = model(store, gateway_id, loc, now, fetch=fetch)
    temps = _forecast_temps(fc or {})
    first = int(now) // 3600 * 3600
    hours = [{"start": first + i * 3600, "temp_c": temps.get(first + i * 3600)}
             for i in range(HORIZON_H)]
    return hforecast.predict_load(m, hours, baseline_kwh=baseline_kwh)


def ha_payload(store, settings, gateway_id: str, now: float | None = None, *,
               fetch=None) -> dict | None:
    """The ``Load Forecast`` sensor's payload: this hour's kW and HAEO's ``forecast``
    series, or None when nothing can be predicted yet. Never raises."""
    from . import site_location, solar_forecast
    now = time.time() if now is None else now
    try:
        loc = site_location.for_gateway(settings, store, gateway_id)
        fc = None
        if site_location.configured(loc) and loc.get("kwp"):
            fc = solar_forecast.forecast(loc["latitude"], loc["longitude"], kwp=loc["kwp"],
                                         tilt=loc["pv_tilt"], azimuth=loc["pv_azimuth"],
                                         store=store)
        pts = predict(store, gateway_id, loc, fc, now, fetch=fetch)
        # an hour's kWh is its mean kW
        series = [{"start": p["start"], "kw": p["kwh"]} for p in pts if p["kwh"] is not None]
        if not series:
            return None
        return {"kw": series[0]["kw"], "method": pts[0]["method"],
                "forecast": hforecast.haeo(series, tz=_zone(store))}
    except Exception as e:                                       # noqa: BLE001
        log.debug("load forecast not worked out: %s", e)
        return None


def backtest(store, settings, gateway_id: str, now: float, *, fetch=None) -> dict | None:
    """``hems.forecast.backtest_load`` over the last ``BACKTEST_DAYS``: the model against
    the cold start and persistence. None without the history for it. Never raises."""
    from . import site_location
    try:
        tz = _zone(store)
        if settings is None:
            from .config import get_settings
            settings = get_settings()
        loc = site_location.for_gateway(settings, store, gateway_id)
        rows = history(store, gateway_id, loc, tz, now, BACKTEST_DAYS, fetch=fetch)
        res = hforecast.backtest_load(rows, tz=tz)
        return res if res.get("days") else None
    except Exception as e:                                       # noqa: BLE001
        log.debug("load forecast backtest failed: %s", e)
        return None
