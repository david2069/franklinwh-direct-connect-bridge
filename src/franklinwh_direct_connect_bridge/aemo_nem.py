"""AEMO NEM wholesale spot price — a built-in dynamic-tariff input (FEAT-BILLING-WHOLESALE).

Uses AEMO's public NEM dashboard data (ELEC_NEM_SUMMARY) — the current 5-minute regional
Reference Price (RRP, $/MWh). NO auth, NO vendor key, NO account. c/kWh = RRP / 10.
Amber and other retailers come in via an HA entity sensor instead (owner's rule: only the
AusNEM built-in + HA sensors as pricing inputs — never a hardcoded vendor API).
"""
from __future__ import annotations

import json
import time as _time
import urllib.request
from typing import Any

#: The five NEM regions (AEMO REGIONID).
REGIONS = ("NSW1", "QLD1", "SA1", "TAS1", "VIC1")

_URL = "https://visualisations.aemo.com.au/aemo/apps/api/report/ELEC_NEM_SUMMARY"
_TTL = 240.0                       # NEM dispatch is 5-min; cache ~4min so we're never stale-by-much
#: How old the last good price may be when a fetch fails (#207). Kept forever, a price-gated
#: force ran on a price that no longer existed. 30 minutes, as on the Modbus Bridge.
_STALE_MAX = 1800.0
_cache: dict[str, tuple] = {}      # region -> (expires_monotonic, dict, fetched_monotonic)


def spot_price(region: str | None) -> dict[str, Any] | None:
    """Current wholesale spot for a NEM region, or None. Never raises; on a fetch error keeps
    the last good value for up to ``_STALE_MAX`` seconds, then None. Returns {region, rrp_mwh,
    price_c_kwh, settlement, source}."""
    region = (region or "").upper()
    if region not in REGIONS:
        return None
    now = _time.monotonic()
    hit = _cache.get(region)
    if hit and hit[0] > now:
        return hit[1]
    try:
        req = urllib.request.Request(
            _URL, headers={"Accept": "application/json", "User-Agent": "franklinwh-direct-connect-bridge"})
        with urllib.request.urlopen(req, timeout=12) as r:
            data = json.load(r)
        for row in (data.get("ELEC_NEM_SUMMARY") or []):
            if row.get("REGIONID") == region and row.get("PRICE") is not None:
                rrp = float(row["PRICE"])
                out = {"region": region, "rrp_mwh": round(rrp, 2),
                       "price_c_kwh": round(rrp / 10.0, 2),
                       "settlement": row.get("SETTLEMENTDATE"), "source": "AEMO NEM"}
                _cache[region] = (now + _TTL, out, now)
                return out
    except Exception:                                          # noqa: BLE001 — market data is optional
        pass
    # Keep stale rather than nothing — but only while it is recent enough to act on.
    return hit[1] if (hit and now - hit[2] <= _STALE_MAX) else None
