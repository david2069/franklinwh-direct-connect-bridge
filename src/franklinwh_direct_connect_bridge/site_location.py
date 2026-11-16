"""Each site's location and PV array (#675).

The bridge used one location and array for the whole install, set from the active
gateway, so every gateway was assumed to be at the same place. Now each site has its own:

* the **default site** keeps the values Location & Solar always had (Settings
  ``pv_latitude`` … ``pv_azimuth``), so a one-site install is unchanged;
* every **other site** has its own, on its row (``sites.latitude`` … ``pv_azimuth``).

A gateway uses its site's: gateway → meter → site, and a gateway with no meter (or a
meter with no site) is on the default site. The PV size is the site's own number, else
what the site's gateways report (``pv_size.derived_kwp``), as #583.

``check`` compares the location each gateway reports (1201 ``time_location``) with its
site's, so a gateway that is somewhere else shows up rather than being assumed.
"""
from __future__ import annotations

import math
from typing import Any, Callable

from . import config

#: The Location & Solar fields, as the site row and the API name them.
FIELDS = ("latitude", "longitude", "pv_kwp", "pv_tilt", "pv_azimuth")
#: The default site's are these settings.
SETTING = {"latitude": "pv_latitude", "longitude": "pv_longitude", "pv_kwp": "pv_kwp",
           "pv_tilt": "pv_tilt", "pv_azimuth": "pv_azimuth"}
#: A gateway within this many km of its site's location is at the same place.
SAME_PLACE_KM = 1.0


def default_site(store) -> dict | None:
    sites = store.sites() if store is not None else []
    return next((x for x in sites if x.get("is_default")), sites[0] if sites else None)


def is_default(store, site: dict | None) -> bool:
    if site is None:
        return True
    d = default_site(store)
    return d is None or d["id"] == site["id"]


def _site_id_of(store, gw_row: dict, meters: dict, sites: dict) -> str | None:
    m = meters.get(gw_row.get("meter_id") or "")
    sid = (m or {}).get("site_id") or ""
    return sid if sid in sites else None


def site_of_gateway(store, gateway_id: str | None) -> dict | None:
    """The gateway's site, else the default site (None when there are no sites)."""
    if store is None:
        return None
    sites = {x["id"]: x for x in store.sites()}
    meters = {m["id"]: m for m in store.meters()}
    row = next((g for g in store.gateways() if g.get("id") == gateway_id), None)
    sid = _site_id_of(store, row, meters, sites) if row else None
    return sites[sid] if sid else default_site(store)


def gateway_ids(store, site: dict | None) -> list[str] | None:
    """The gateways on ``site``: those whose meter is on it, and, for the default site,
    those with no site. None (every gateway) without a store: one site, as before."""
    if store is None:
        return None
    sites = {x["id"]: x for x in store.sites()}
    meters = {m["id"]: m for m in store.meters()}
    default = is_default(store, site)
    out = []
    for g in store.gateways():
        sid = _site_id_of(store, g, meters, sites)
        if (sid is None and default) or (site is not None and sid == site["id"]):
            out.append(g["id"])
    return out


def values(settings, store, site: dict | None) -> dict[str, Any]:
    """The site's latitude, longitude and PV array, as set (None = not set)."""
    if is_default(store, site):
        return {f: getattr(settings, SETTING[f], None) for f in FIELDS}
    return {f: site.get(f) for f in FIELDS}


def save(settings, store, site: dict | None, fields: dict) -> dict[str, Any]:
    """Save some of the site's fields (None clears one). The default site's go to
    Location & Solar's settings, live and persisted; another site's to its row."""
    vals = {k: (None if v is None else float(v)) for k, v in fields.items() if k in FIELDS}
    if is_default(store, site):
        for k, v in vals.items():
            config.save_override(SETTING[k], v)
            setattr(settings, SETTING[k], v)
    else:
        store.set_site_location(site["id"], **vals)
        site = store.site(site["id"])
    return values(settings, store, site)


def _derived(ids: list[str] | None) -> float | None:
    from . import pv_size
    return pv_size.derived_kwp(gateway_ids=ids)


def effective(settings, store, site: dict | None, *,
              derived: Callable[[list[str]], float | None] | None = None) -> dict[str, Any]:
    """The site's values with the PV size the forecast uses: ``kwp`` (the site's own,
    ``kwp_source`` you, else its gateways', gateway) and ``derived`` (the gateways')."""
    v = values(settings, store, site)
    d = (derived or _derived)(gateway_ids(store, site))
    mine = v["pv_kwp"]
    if isinstance(mine, (int, float)) and mine > 0:
        kwp, src = float(mine), "you"
    else:
        kwp, src = d, "gateway" if d else None
    return {**v, "kwp": kwp, "kwp_source": src, "derived": d,
            "site_id": site["id"] if site else None}


def for_gateway(settings, store, gateway_id: str | None, **kw) -> dict[str, Any]:
    """``effective`` for the gateway's site."""
    return effective(settings, store, site_of_gateway(store, gateway_id), **kw)


def configured(loc: dict) -> bool:
    return loc.get("latitude") is not None and loc.get("longitude") is not None


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance (haversine)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(a))


def check(loc: dict, reported: dict[str, dict | None]) -> list[dict]:
    """Each gateway's reported location against the site's: ``distance_km`` and
    ``same_place`` (within SAME_PLACE_KM). None when either location is unknown."""
    out = []
    for gid, r in reported.items():
        lat, lon = (r or {}).get("latitude"), (r or {}).get("longitude")
        row = {"gateway_id": gid, "latitude": lat, "longitude": lon,
               "distance_km": None, "same_place": None}
        if lat is not None and lon is not None and configured(loc):
            d = distance_km(loc["latitude"], loc["longitude"], lat, lon)
            row.update(distance_km=round(d, 1), same_place=d <= SAME_PLACE_KM)
        out.append(row)
    return out
