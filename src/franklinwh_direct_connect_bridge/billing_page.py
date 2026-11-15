"""The Billing & Utilities page (#613, #629): which meter, what is still to set up, and the
meter's plans as OUTUS plans.

The setup steps (site → meter → plan → tariffs) come from hems, the OUTUS engine, so the
page, Explain and the scheduler's messages all say the same thing. A bridge tariff becomes
an OUTUS plan through its tariff-profile export, which hems imports.
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from hems import profile_v1, setup

from . import tariff_io


def _meters(store) -> list[dict[str, Any]]:
    """Every meter with its site and the enabled gateways that feed it (default first)."""
    gws = [g for g in store.gateways() if g.get("enabled", 1)]
    gws.sort(key=lambda g: not g.get("is_default"))
    out = []
    for m in store.meters():
        out.append({"id": m["id"], "name": m.get("name") or "Meter", "site_id": m.get("site_id"),
                    "is_default": bool(m.get("is_default")),
                    "gateway_ids": [g["id"] for g in gws if g.get("meter_id") == m["id"]]})
    out.sort(key=lambda m: not m["is_default"])
    return out


def outus_plan(store, tariff_id: str) -> dict[str, Any] | None:
    """One bridge tariff as an OUTUS plan (``outus/plan``), or None when there is none."""
    tar = store.tariff(tariff_id)
    if not tar:
        return None
    util = store.utility(tar["utility_id"]) if tar.get("utility_id") else None
    meter = store.meter(tar["meter_id"]) if tar.get("meter_id") else None
    plan = profile_v1.from_tariff_profile(
        tariff_io.from_local(util, tar, (meter or {}).get("timezone") or ""))
    plan["id"] = tar["id"]
    # The bridge keeps the billing day on the tariff, not in the profile's pricing.
    plan["billing"]["cycle_day"] = max(1, min(28, int(tar.get("billing_cycle_day") or 1)))
    if (util or {}).get("name"):
        plan["retailer"]["name"] = util["name"]
    return plan


def _plans(store, meter_id: str) -> list[dict[str, Any]]:
    return [p for t in store.tariffs() if t.get("meter_id") == meter_id
            for p in [outus_plan(store, t["id"])] if p]


def page(store, meter_id: str | None, today: dt.date) -> dict[str, Any]:
    """The meters to choose from, the chosen one (``meter_id``, else the default) and its
    setup steps."""
    meters = _meters(store)
    meter = next((m for m in meters if m["id"] == meter_id), None) or (meters[0] if meters else None)
    steps = setup.steps(store.sites(), meters, _plans(store, meter["id"]) if meter else [],
                        meter["id"] if meter else None, today)
    return {"meters": meters, "meter": meter, "steps": steps, "complete": setup.complete(steps)}
