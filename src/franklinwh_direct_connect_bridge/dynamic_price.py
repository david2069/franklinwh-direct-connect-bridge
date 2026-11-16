"""Generic dynamic-pricing attributes (owner 2026-11-16).

One list of what a dynamic price source can tell the scheduler, whatever the source: the
buy and feed-in price, their forecasts and descriptors, the grid's renewables share, a
price spike and a demand window. Each comes from a Home Assistant entity when one is set;
AEMO NEM gives the buy price only. A source that has no such value leaves it **None**
(Home Assistant's "unknown", the scheduler's "no value"), never NaN: NaN can't go into
JSON or MQTT and reads as a number.

``related`` finds the rest of a retailer integration's sensors from one of them, so
picking Amber Electric's price fills the others (please confirm).
"""
from __future__ import annotations

from typing import Any

#: Every attribute: its scheduler sensor, the setting naming its HA entity, and its kind
#: (``price`` c/kWh, ``pct``, ``text``, ``on`` for a binary sensor).
ATTRIBUTES: list[dict[str, str]] = [
    {"sensor": "tariff.spot_price", "setting": "tariff_price_entity", "kind": "price",
     "label": "Buy price"},
    {"sensor": "tariff.feed_in_price", "setting": "tariff_feedin_entity", "kind": "price",
     "label": "Feed-in price"},
    {"sensor": "tariff.price_forecast", "setting": "tariff_price_forecast_entity",
     "kind": "price", "label": "Buy price forecast"},
    {"sensor": "tariff.feed_in_forecast", "setting": "tariff_feedin_forecast_entity",
     "kind": "price", "label": "Feed-in price forecast"},
    {"sensor": "tariff.price_descriptor", "setting": "tariff_price_descriptor_entity",
     "kind": "text", "label": "Buy price descriptor"},
    {"sensor": "tariff.feed_in_descriptor", "setting": "tariff_feedin_descriptor_entity",
     "kind": "text", "label": "Feed-in price descriptor"},
    {"sensor": "tariff.renewables_pct", "setting": "tariff_renewables_entity", "kind": "pct",
     "label": "Renewables on the grid"},
    {"sensor": "tariff.price_spike", "setting": "price_spike_entity", "kind": "on",
     "label": "Price spike"},
    {"sensor": "tariff.demand_window_active", "setting": "demand_window_entity", "kind": "on",
     "label": "Demand window"},
]

#: Retailer integrations whose sensors share a site prefix: {setting: (domain, suffix)}.
#: Amber Electric (the HA core integration): sensor.<site>_general_price and so on.
FAMILIES: dict[str, dict[str, tuple[str, str]]] = {
    "Amber Electric": {
        "tariff_price_entity": ("sensor", "_general_price"),
        "tariff_feedin_entity": ("sensor", "_feed_in_price"),
        "tariff_price_forecast_entity": ("sensor", "_general_forecast"),
        "tariff_feedin_forecast_entity": ("sensor", "_feed_in_forecast"),
        "tariff_price_descriptor_entity": ("sensor", "_general_price_descriptor"),
        "tariff_feedin_descriptor_entity": ("sensor", "_feed_in_price_descriptor"),
        "tariff_renewables_entity": ("sensor", "_renewables"),
        "price_spike_entity": ("binary_sensor", "_price_spike"),
        "demand_window_entity": ("binary_sensor", "_demand_window"),
    },
}


def _split(sid: str) -> tuple[str, str] | None:
    sid = (sid or "").strip()
    if sid.startswith("ha:") and sid.count(":") >= 2:
        _, inst, eid = sid.split(":", 2)
        return inst, eid
    return None


def related(sid: str, states: list[dict]) -> dict[str, str]:
    """The settings a retailer integration can fill, from one of its sensors (``sid``,
    ``ha:<inst>:<entity>``) and that HA's states: only sensors that exist. ``{}`` when
    ``sid`` is not one a known integration names."""
    parts = _split(sid)
    if not parts:
        return {}
    inst, eid = parts
    have = {s.get("entity_id") for s in states}
    for fam in FAMILIES.values():
        site = None
        for dom, suffix in fam.values():
            if eid.startswith(dom + ".") and eid.endswith(suffix):
                cand = eid[len(dom) + 1:-len(suffix)]
                # the longest suffix that fits wins (_feed_in_price vs _price)
                if site is None or len(cand) < len(site):
                    site = cand
        if not site:
            continue
        out = {setting: f"ha:{inst}:{dom}.{site}{suffix}" for setting, (dom, suffix) in fam.items()
               if f"{dom}.{site}{suffix}" in have}
        if out:
            return out
    return {}


def _states(store, ids) -> dict[str, dict]:
    """The given ``ha:<inst>:<entity>`` entities' state objects, read from their instances
    (bounded to those). Never raises; an unreadable one is absent."""
    from . import ha_instances
    want: dict[str, dict[str, str]] = {}
    for sid in ids:
        parts = _split(sid)
        if parts:
            want.setdefault(parts[0], {})[parts[1]] = sid
    if not want or store is None:
        return {}
    try:
        insts = {i["id"]: i for i in store.ha_instances()}
    except Exception:                                           # noqa: BLE001
        return {}
    out: dict[str, dict] = {}
    for inst_id, eids in want.items():
        inst = insts.get(inst_id)
        if not inst or not inst.get("enabled"):
            continue
        try:
            for st in ha_instances.states(inst["base_url"], inst.get("token")):
                if st.get("entity_id") in eids:
                    out[eids[st["entity_id"]]] = st
        except Exception:                                       # noqa: BLE001
            continue
    return out


def _value(kind: str, st: dict) -> Any:
    from .scheduler import _ha_price_to_c_kwh
    state = st.get("state")
    if state in (None, "", "unknown", "unavailable"):
        return None
    if kind == "price":
        return _ha_price_to_c_kwh(st)
    if kind == "pct":
        try:
            return round(float(state), 2)
        except (TypeError, ValueError):
            return None
    return str(state)


def read(settings, store) -> dict[str, Any]:
    """The attributes whose HA entity is set and readable. The spike and demand-window
    sensors are read too, under their own ``ha:`` ids, so ``price_events`` finds them
    even when they aren't exposed (it used to see exposed entities only)."""
    from .scheduler import _coerce
    ids = {a["sensor"]: (getattr(settings, a["setting"], "") or "").strip() for a in ATTRIBUTES}
    got = _states(store, [i for i in ids.values() if i])
    out: dict[str, Any] = {}
    for a in ATTRIBUTES:
        st = got.get(ids[a["sensor"]])
        if st is None:
            continue
        if a["kind"] == "on":
            out[ids[a["sensor"]]] = _coerce(st.get("state"))
            continue
        v = _value(a["kind"], st)
        if v is not None:
            out[a["sensor"]] = v
    return out


def fill_missing(snapshot: dict) -> None:
    """Every attribute in the snapshot: a source without one leaves it None."""
    for a in ATTRIBUTES:
        snapshot.setdefault(a["sensor"], None)
