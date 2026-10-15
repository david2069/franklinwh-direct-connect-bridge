"""A copy-paste Home Assistant dashboard card for the entities this bridge publishes.

Shape agreed across the FranklinWH integrations (``fwhai`` shipped first, commit 92991e3):
plain core cards only, no custom cards, no theme line, and **never a guessed entity id**.

The id rule matters. We publish by MQTT discovery and set ``object_id``, so Home Assistant
builds ``<domain>.<object_id>`` — deterministic, *until* it collides with an existing entity
and HA appends ``_2``. So every id in the output is one HA actually reports: we look for the
candidate, accept a numeric suffix of it, and anything we cannot find is reported as missing
rather than guessed into the YAML.

``fwhai`` reads HA's entity registry over the websocket to do this. We do not, for one
reason: the registry is websocket-only and there is no websocket client in this image, while
``object_id`` gives us an exact candidate to confirm against the REST ``/api/states`` we
already use. The trade-off is renames — an entity the user renamed in HA keeps its id, so
this still finds it, but one whose *entity id* was changed by hand will be reported missing.
That is the correct failure: visible, and not a wrong id.
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
        rows.append({"domain": "sensor", "object_id": f"franklinwh_{node}_{e['key']}",
                     "name": e["name"], "group": g})
    if "controls" in enabled:
        for c in ents.CONTROLS:
            rows.append({"domain": c["ha_type"],
                         "object_id": f"franklinwh_{node}_{c['key']}",
                         "name": c["name"], "group": "controls"})
    return rows


def resolve_ids(rows: list[dict], ha_entity_ids: set[str]) -> tuple[list[dict], list[dict]]:
    """Split rows into (found, missing), attaching the REAL entity id to each found row.

    A row matches ``<domain>.<object_id>`` exactly, or that with a numeric suffix, which is
    how HA disambiguates a collision. Nothing else is accepted — a near miss is a miss.
    """
    found, missing = [], []
    for r in rows:
        want = f"{r['domain']}.{r['object_id']}"
        if want in ha_entity_ids:
            found.append({**r, "entity_id": want})
            continue
        suffixed = sorted(
            e for e in ha_entity_ids
            if e.startswith(want + "_") and e[len(want) + 1:].isdigit()
        )
        if suffixed:
            found.append({**r, "entity_id": suffixed[0]})
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
