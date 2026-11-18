"""What FranklinWH entities Home Assistant already has, before this bridge publishes (#741).

Two sources, each optional:

* the broker's RETAINED discovery configs (``mqtt_scan.scan_orphans``): this bridge's
  live nodes, its leftovers from removed gateways, and other producers (the Modbus
  Bridge, FWHAI, another Direct Connect bridge);
* Home Assistant's registry, when HA is linked (``ha_instances.franklin_devices``):
  FranklinWH MQTT devices on any broker, and true ``_2`` duplicates.

Only this bridge's OWN leftovers may be removed (the existing guarded purge). Everything
else is reported and left alone. A cloud integration that is not MQTT is not seen here,
except richo's ``franklin_wh``: an optional note, read from HA's loaded components.
"""
from __future__ import annotations

from typing import Any

#: Stored in the config table once the owner picks Keep both on the richo note.
RICHO_KEY = "setup_richo_note"
RICHO_DOMAIN = "franklin_wh"

#: What this bridge adds over richo's integration (2026.3.0, cloud_polling: whole-system
#: power and energy sensors and Smart Circuit switches). Only what both sides were read for.
RICHO_ADDS = [
    "Reads the aGate on your own network; the FranklinWH cloud is optional.",
    "Operating mode, reserve and battery dispatch controls in Home Assistant.",
    "The scheduler, with actionable notifications on your phone.",
    "Alerts when the aGate can't be reached, its data stops, or a command or schedule fails.",
    "Each aPower's charge, health and state in the bridge.",
]


def _ours_sw(sw: str) -> bool:
    from .publish import mqtt_scan
    return mqtt_scan._is_ours(sw)


def _same_agate(dev: dict, serials: list[str]) -> bool:
    text = " ".join(str(x) for x in ([dev.get("identifier"), dev.get("serial_number")]
                                     + list(dev.get("identifiers") or []))).lower()
    return any(s and s.lower() in text for s in serials)


def inventory(*, broker: dict | None, registry: list[dict] | None, components: list[str],
              serials: list[str], richo_dismissed: bool, purge_ready: bool) -> dict[str, Any]:
    """The rows the wizard shows. Pure: the caller does the reads."""
    rows: list[dict[str, Any]] = []
    others: list[dict] = []
    b = broker or {}
    if b.get("ok"):
        orphans = b.get("orphans") or []
        n = sum(g.get("entities", 0) for g in orphans)
        if n:
            rows.append({"kind": "ours_orphan", "who": "This bridge (removed gateways)",
                         "what": f"{len(orphans)} old device(s)", "entities": n,
                         "action": "remove" if purge_ready else "report",
                         "expect": n,
                         "advice": ("Remove them: Home Assistant re-creates them on every "
                                    "restart." if purge_ready else
                                    "Remove them from the MQTT tab once publishing is on.")})
        others = list(b.get("foreign") or [])
    # Registry devices that are not ours and not already seen on this broker.
    seen = {g.get("identifier") for g in others}
    for d in registry or []:
        idents = d.get("identifiers") or []
        if not _ours_sw(d.get("sw_version") or "") and not (set(idents) & seen):
            others.append({"identifier": idents[0] if idents else "", "name": d.get("name"),
                           "sw_version": d.get("sw_version"), "entities": d.get("entities", 0),
                           "identifiers": idents})
        if d.get("dup2"):
            rows.append({"kind": "dup2", "who": d.get("sw_version") or d.get("name") or "?",
                         "what": d.get("name") or "", "entities": d["dup2"], "action": "report",
                         "advice": ("Entity ids ending in _2: an older entity holds the name. "
                                    "Home Assistant → Settings → Entities: remove the old one, "
                                    "then rename the _2.")})
    same = modbus = False
    for g in others:
        who = g.get("sw_version") or g.get("name") or g.get("identifier") or "?"
        is_same = _same_agate(g, serials)
        is_mb = "modbus bridge" in who.lower()
        same = same or is_same
        modbus = modbus or (is_mb and (is_same or not serials))
        rows.append({"kind": "other", "who": who, "what": g.get("name") or "",
                     "entities": g.get("entities", 0), "same_agate": is_same,
                     "action": "report",
                     "advice": ("Publishes this aGate too: keep one, or turn off its "
                                "publishing." if is_same else
                                "Another FranklinWH integration; left as it is.")})
    richo = RICHO_DOMAIN in (components or [])
    return {
        "rows": rows,
        "broker": ({"checked": True} if b.get("ok") else
                   {"checked": False, "why": b.get("error") or "no broker set up yet"}),
        "registry": ({"checked": True} if registry is not None else
                     {"checked": False, "why": "Home Assistant is not linked"}),
        "other_same_agate": same,
        "modbus_writer": modbus,
        "richo": {"show": richo and not richo_dismissed, "adds": RICHO_ADDS},
    }
