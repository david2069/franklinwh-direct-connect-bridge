"""A copy-paste Home Assistant dashboard card for the entities this bridge publishes.

Shape agreed across the FranklinWH integrations (``fwhai`` shipped first, commit 92991e3):
plain core cards only, no custom cards, no theme line, and **never a guessed entity id**.

The id rule matters. We publish by MQTT discovery with an ``object_id``, but Home Assistant
names the entity after the DEVICE and the entity name (``sensor.franklinwh_direct_<last 8
of serial>_state_of_charge``), and appends ``_2`` on a collision. Composing ids from
``object_id`` found none of them (#689). So we ask HA for the entity ids of this gateway's
own device (by its discovery identifier) and match each published entity by its name;
installs whose ids still follow ``object_id`` match that way. Anything we cannot find is
reported as missing rather than guessed into the YAML.

``fwhai`` reads HA's entity registry over the websocket. We use HA's template engine on
the REST API instead (there is no websocket client in this image). An entity whose id
was changed by hand in HA is reported missing: visible, and not a wrong id.
"""
from __future__ import annotations

import re
from typing import Any

#: Our publish groups -> the card titles, in display order. Diagnostics last and opt-in.
GROUP_TITLES: list[tuple[str, str]] = [
    ("core", "Core"),
    ("power", "Power"),
    ("energy", "Energy"),
    ("controls", "Controls"),
    ("diagnostic", "Diagnostics"),
]

#: Only emitted when the caller asks for them.
DIAGNOSTIC_GROUPS = {"diagnostic"}

_SUFFIXED = re.compile(r"^(?P<base>.+?)(?:_(?P<n>\d+))?$")


def rows_for_node(node: str, groups=None) -> list[dict[str, Any]]:
    """What this bridge publishes for ``node``, as {domain, object_id, name, group} rows.

    Built from the ENTITY DEFINITIONS rather than from the rendered discovery configs: the
    configs do not carry the group, and re-deriving it from the topic would mean a second
    source of truth for which entity belongs where.
    """
    from .publish import entities as ents

    enabled = ents._enabled(groups)
    rows: list[dict[str, Any]] = []
    for e in ents.ENTITIES:
        g = e.get("group", "core")
        if g not in enabled:
            continue
        rows.append({"domain": e.get("ha_type", "sensor"),
                     "object_id": f"franklinwh_{node}_{e['key']}",
                     "name": e["name"], "group": g})
    if "controls" in enabled:
        for c in ents.CONTROLS:
            rows.append({"domain": c["ha_type"],
                         "object_id": f"franklinwh_{node}_{c['key']}",
                         "name": c["name"], "group": "controls"})
    return rows


def slug(text: str) -> str:
    """Home Assistant's slugify for an entity id: lower case, anything else becomes ``_``."""
    return re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")


def _with_suffix(want: str, ids: set[str]) -> str | None:
    """``want`` itself, or that with HA's numeric collision suffix; nothing else."""
    if want in ids:
        return want
    suffixed = sorted(e for e in ids
                      if e.startswith(want + "_") and e[len(want) + 1:].isdigit())
    return suffixed[0] if suffixed else None


def _device_prefix(rows: list[dict], device_ids: set[str]) -> str | None:
    """The part HA put before the entity name in this device's ids (the device name when
    the entity was created): the prefix most of the device's ids share with a row name."""
    tails = [(r["domain"], "_" + slug(r["name"])) for r in rows]
    votes: dict[str, int] = {}
    for eid in device_ids:
        domain, _, obj = eid.partition(".")
        if not any(obj.endswith(t) for _d, t in tails):
            obj = re.sub(r"_\d+$", "", obj)          # HA's collision suffix, e.g. _2
        for d, tail in tails:
            if d == domain and obj.endswith(tail) and len(obj) > len(tail):
                p = obj[:-len(tail)]
                votes[p] = votes.get(p, 0) + 1
    return max(votes, key=lambda p: (votes[p], -len(p))) if votes else None


def resolve_ids(rows: list[dict], ha_entity_ids: set[str],
                device_ids: set[str] | None = None) -> tuple[list[dict], list[dict]]:
    """Split rows into (found, missing), attaching the REAL entity id to each found row.

    With ``device_ids`` (this gateway's device's entity ids, from HA), a row matches
    ``<domain>.<device prefix>_<slug of its name>`` among them (#689). Otherwise, or when
    that finds nothing, ``<domain>.<object_id>``. Either may carry HA's numeric collision
    suffix. Only ids HA reports a state for are used — a near miss is a miss.
    """
    own = (set(device_ids) & ha_entity_ids) if device_ids else set()
    prefix = _device_prefix(rows, own) if own else None
    found, missing = [], []
    for r in rows:
        eid = None
        if prefix:
            eid = _with_suffix(f"{r['domain']}.{prefix}_{slug(r['name'])}", own)
        if not eid:
            eid = _with_suffix(f"{r['domain']}.{r['object_id']}", ha_entity_ids)
        if eid:
            found.append({**r, "entity_id": eid})
        else:
            missing.append(r)
    return found, missing


def _entities_card(title: str, ids: list[str]) -> list[str]:
    out = [
        "  - type: entities",
        f"    title: {title}",
        "    show_header_toggle: false",
        "    state_color: true",
        "    entities:",
    ]
    out += [f"      - entity: {e}" for e in ids]
    return out


def build_yaml(found: list[dict], *, layout: str = "grouped",
               diagnostics: bool = False, integration: str = "FranklinWH Direct Connect",
               ) -> str:
    """The YAML, as plain core cards. Empty groups are omitted, not emitted blank."""
    rows = [r for r in found if diagnostics or r["group"] not in DIAGNOSTIC_GROUPS]
    if not rows:
        return ""

    if layout == "single":
        lines = ["type: entities", f"title: {integration}",
                 "show_header_toggle: false", "state_color: true", "entities:"]
        lines += [f"  - entity: {r['entity_id']}" for r in rows]
        return "\n".join(lines) + "\n"

    lines = ["type: vertical-stack", "cards:"]
    for group, title in GROUP_TITLES:
        ids = [r["entity_id"] for r in rows if r["group"] == group]
        if ids:
            lines += _entities_card(f"{integration} — {title}", ids)
    return "\n".join(lines) + "\n"
