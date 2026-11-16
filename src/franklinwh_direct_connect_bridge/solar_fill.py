"""Will the solar left today fill the battery? (#676)

The forecast's hourly kW for the rest of today (location-local, as Open-Meteo gives it)
against what the battery needs to reach 100 %: capacity × (100 − SoC). Home use is not
taken off, so "won't fill" is the honest direction: if even all of the solar can't do it,
it won't. The card shows the answer; the ``solar_wont_fill`` trigger sends it once a day
while solar is still forecast.
"""
from __future__ import annotations

import datetime as dt
import logging

log = logging.getLogger(__name__)

#: app_config key: the site day the warning last went out, per gateway.
SENT_KEY = "solar_wont_fill_sent:{gw}"
#: A forecast hour below this (kW) is no sun.
SUN_KW = 0.05


def _local(ts: float, off: int) -> dt.datetime:
    return dt.datetime.fromtimestamp(ts, dt.timezone(dt.timedelta(seconds=off)))


def assess(fc: dict, *, soc, capacity_kwh, now_ts: float) -> dict | None:
    """``{remaining_kwh, needed_kwh, soc, capacity_kwh, will_fill, sun_left, day}``; with no
    capacity, ``{"needs": "battery capacity"}``; None without a SoC or a forecast."""
    hours = (fc or {}).get("hourly") or []
    if soc is None or not hours:
        return None
    if not capacity_kwh:
        return {"needs": "battery capacity"}
    now = _local(now_ts, int(fc.get("utc_offset_seconds") or 0))
    day = now.date().isoformat()
    frac = now.minute / 60
    remaining, sun_left = 0.0, False
    for h in hours:
        t = h.get("time") or ""
        if t[:10] != day:
            continue
        hr, kw = int(t[11:13] or 0), float(h.get("kw") or 0)
        if hr > now.hour:
            part = kw
        elif hr == now.hour:
            part = kw * (1 - frac)
        else:
            continue
        remaining += part
        sun_left = sun_left or kw >= SUN_KW
    needed = max(0.0, float(capacity_kwh) * (100 - float(soc)) / 100)
    return {"remaining_kwh": round(remaining, 2), "needed_kwh": round(needed, 2),
            "soc": round(float(soc)), "capacity_kwh": float(capacity_kwh),
            "will_fill": remaining >= needed, "sun_left": sun_left, "day": day}


def check(store, gateway_id: str, gateway_name: str, fc: dict, *, soc, capacity_kwh,
          now_ts: float) -> bool:
    """Send ``solar_wont_fill`` when today's solar won't fill the battery, while there is
    still sun forecast, once a site day per gateway. True when it was sent."""
    from . import notify_engine
    a = assess(fc, soc=soc, capacity_kwh=capacity_kwh, now_ts=now_ts)
    if not a or "needs" in a or a["will_fill"] or not a["sun_left"] or a["soc"] >= 100:
        return False
    key = SENT_KEY.format(gw=gateway_id)
    if store.get_config(key) == a["day"]:
        return False
    store.set_config(key, a["day"])
    notify_engine.fire(store, "solar_wont_fill", gateway=gateway_name,
                       remaining=f"{a['remaining_kwh']:.1f}", needed=f"{a['needed_kwh']:.1f}",
                       soc=a["soc"])
    return True


def check_gateway(store, settings, gateway_id: str, gateway_name: str, soc,
                  now_ts: float) -> bool:
    """``check`` for a gateway: its site's forecast (cached; no fetch while the trigger
    is off) and the Battery capacity constant. Never raises."""
    from . import constants, notify_engine, site_location, solar_forecast
    try:
        if not notify_engine._enabled(notify_engine.config(store), "solar_wont_fill"):
            return False
        loc = site_location.for_gateway(settings, store, gateway_id)
        if not site_location.configured(loc) or not loc["kwp"]:
            return False
        fc = solar_forecast.forecast(loc["latitude"], loc["longitude"], kwp=loc["kwp"],
                                     tilt=loc["pv_tilt"], azimuth=loc["pv_azimuth"])
        cap = constants.values(store).get("battery_capacity_kwh")
        return check(store, gateway_id, gateway_name, fc, soc=soc, capacity_kwh=cap,
                     now_ts=now_ts)
    except Exception as e:  # noqa: BLE001 — a notification never breaks the poll
        log.debug("solar fill check failed: %s", e)
        return False
