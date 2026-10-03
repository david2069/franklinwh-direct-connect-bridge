"""Tariff-profile interchange with the Modbus bridge (FEAT-IMPORT-AGL-SETUP).

The Modbus bridge exports a utility service's tariff as a ``franklinwh-bridge/tariff-profile``
bundle. This maps it BOTH ways to our utilities + tariffs schema, so the two bridges interchange
a full retailer/plan (e.g. "AGL Energy Ausgrid NSW") without re-typing rates.

The only shape difference is that the Modbus profile NESTS the export-charge as
``pricing.export_charge = {window, rate, free_kwh_per_day}`` and keeps ``fixed_charges`` under
pricing, whereas our billing engine reads FLAT ``pricing.export_charge_rate`` /
``export_charge_free_kwh_per_day`` + a separate ``charge_window`` column + a ``fixed_charges``
column. `to_local` flattens; `from_local` re-nests. The seasons block (months + blocks +
time_periods{buy,sell}) is already identical to what ``rate_model.resolve`` expects.
"""
from __future__ import annotations

from typing import Any

PROFILE_TYPE = "franklinwh-bridge/tariff-profile"
PROFILE_VERSION = 1


def to_local(profile: dict) -> tuple[dict, dict, str | None]:
    """A tariff-profile → (utility_fields, tariff_fields, timezone) for our schema."""
    pr = dict(profile.get("pricing") or {})
    ec = pr.pop("export_charge", None) or {}
    charge_window = ec.get("window") or None
    if ec.get("rate") is not None:
        pr["export_charge_rate"] = ec.get("rate")
    if ec.get("free_kwh_per_day") is not None:
        pr["export_charge_free_kwh_per_day"] = ec.get("free_kwh_per_day")
    fixed = pr.pop("fixed_charges", None) or None
    utility = {
        "name": profile.get("retailer") or profile.get("name") or "Utility",
        "network_dnsp": profile.get("network") or "",
        "country": profile.get("country") or "",
        "plan_type": profile.get("plan_type") or "unknown",
    }
    tariff = {
        "name": profile.get("name") or "Imported tariff",
        "billing_cycle_day": int(pr.get("billing_cycle_day") or 1),
        "pricing": pr,
        "demand_window": profile.get("demand_window") or None,
        "bonus_window": profile.get("bonus_window") or None,
        "charge_window": charge_window,
        "fixed_charges": fixed,
    }
    return utility, tariff, profile.get("timezone")


def from_local(utility: dict | None, tariff: dict, timezone: str | None = None) -> dict:
    """Our utility + tariff → a ``franklinwh-bridge/tariff-profile`` bundle (inverse of to_local)."""
    u = utility or {}
    pr = dict(tariff.get("pricing") or {})
    ec: dict[str, Any] = {}
    if tariff.get("charge_window"):
        ec["window"] = tariff.get("charge_window")
    if pr.get("export_charge_rate") is not None:
        ec["rate"] = pr.pop("export_charge_rate")
    if pr.get("export_charge_free_kwh_per_day") is not None:
        ec["free_kwh_per_day"] = pr.pop("export_charge_free_kwh_per_day")
    if ec:
        pr["export_charge"] = ec
    if tariff.get("fixed_charges"):
        pr["fixed_charges"] = tariff.get("fixed_charges")
    profile = {
        "name": tariff.get("name") or "",
        "retailer": u.get("name") or "",
        "network": u.get("network_dnsp") or "",
        "plan_type": u.get("plan_type") or "unknown",
        "country": u.get("country") or "",
        "timezone": timezone or "",
        "has_tou": 1 if pr.get("seasons") else 0,
        "has_peak_demand": 1 if tariff.get("demand_window") else 0,
        "has_export_bonus": 1 if tariff.get("bonus_window") else 0,
        "min_monthly_bill": 0,
        "demand_window": tariff.get("demand_window") or None,
        "bonus_window": tariff.get("bonus_window") or None,
        "pricing": pr,
    }
    return {"type": PROFILE_TYPE, "version": PROFILE_VERSION, "profile": profile}
