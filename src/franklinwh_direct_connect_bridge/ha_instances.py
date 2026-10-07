"""Talk to one or more Home Assistant instances.

One bridge, many Home Assistants — the single ``HA_URL``/``HA_TOKEN`` pair could
only ever describe one, and a second instance (a test box, a shed, a second house)
had nowhere to live.

Everything here is read-only against HA: list entities, list ``notify.*`` services,
probe a connection. Tokens are passed to HA and never returned to a caller.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

#: HA is on the LAN; a slow instance should not stall a page load.
TIMEOUT_S = 8.0


def _get(base_url: str, token: str | None, path: str,
         timeout: float = TIMEOUT_S) -> Any:
    url = base_url.rstrip("/") + path
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}" if token else "",
        "Content-Type": "application/json",
    })
    if not token:
        # An unauthenticated call returns 401 and looks like a wrong URL; say which.
        raise PermissionError("no token configured for this instance")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def probe(base_url: str, token: str | None) -> dict[str, Any]:
    """Test a connection. Never raises — the result IS the answer."""
    try:
        body = _get(base_url, token, "/api/")
        return {"ok": True, "message": (body or {}).get("message", "connected")}
    except PermissionError as e:
        return {"ok": False, "error": str(e)}
    except urllib.error.HTTPError as e:
        hint = "token rejected" if e.code in (401, 403) else f"HTTP {e.code}"
        return {"ok": False, "error": hint}
    except Exception as e:                                       # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def states(base_url: str, token: str | None) -> list[dict[str, Any]]:
    """Every entity state in one instance."""
    body = _get(base_url, token, "/api/states")
    return body if isinstance(body, list) else []


def notify_targets(base_url: str, token: str | None) -> list[str]:
    """Available ``notify.*`` services.

    Notify targets are SERVICES, not entities, so they never appear in an entity
    list — which is why a notification setting that only says "on" cannot tell you
    where anything was sent.
    """
    body = _get(base_url, token, "/api/services")
    out: list[str] = []
    for domain in body if isinstance(body, list) else []:
        if domain.get("domain") != "notify":
            continue
        for name in (domain.get("services") or {}):
            out.append(f"notify.{name}")
    return sorted(out)


#: A topic is one concept installations name a dozen ways, so each is an OR of
#: substrings — a single word misses most of it ("pv" alone skips "enphase").
TOPICS: dict[str, list[str]] = {
    "Solar / PV": ["solar", "pv", "enphase", "envoy", "fronius", "inverter"],
    "Battery": ["battery", "soc", "charge", "discharge", "powerwall", "apower"],
    "Grid / Export": ["grid", "export", "import", "feed", "site_power"],
    "Price / Tariff": ["price", "tariff", "amber", "cost", "rate", "peak"],
    "Automations": ["automation."],
}


def entities(store, *, instance_id: str | None = None, domain: str | None = None,
             search: str | None = None, topic: str | None = None,
             exposed: bool | None = None, exposed_ids: set | None = None,
             limit: int = 200) -> dict[str, Any]:
    """Entities across the configured instances, filtered.

    A Home Assistant can hold thousands of entities, so this filters and caps
    rather than returning everything. Per-instance errors are reported alongside
    the results instead of failing the whole call — one unreachable instance must
    not hide the others.
    """
    rows: list[dict[str, Any]] = []
    errors: dict[str, str] = {}
    total = 0
    domains: dict[str, int] = {}
    exposed_count = 0
    exposed_ids = exposed_ids or set()
    terms = [t.strip().lower() for t in (search or "").split(",") if t.strip()]
    topic_terms = [t.lower() for t in TOPICS.get(topic or "", [])]
    for inst in store.ha_instances():
        if not inst.get("enabled"):
            continue
        if instance_id and inst["id"] != instance_id:
            continue
        try:
            found = states(inst["base_url"], inst.get("token"))
        except Exception as e:                                   # noqa: BLE001
            errors[inst["id"]] = f"{type(e).__name__}: {e}"
            continue
        for st in found:
            eid = st.get("entity_id", "")
            dom = eid.split(".", 1)[0] if "." in eid else ""
            fname = str((st.get("attributes") or {}).get("friendly_name") or "")
            is_exposed = f"{inst['id']}:{eid}" in exposed_ids
            # Census (domain counts, exposed total) reflects the WHOLE instance,
            # not the filtered page — otherwise the dropdown would shrink as you filter.
            domains[dom] = domains.get(dom, 0) + 1
            if is_exposed:
                exposed_count += 1

            hay = (eid + " " + fname).lower()
            if domain and dom != domain:
                continue
            if terms and not any(t in hay for t in terms):
                continue
            if topic_terms and not any(t in hay for t in topic_terms):
                continue
            if exposed is not None and is_exposed is not exposed:
                continue
            total += 1
            if len(rows) < limit:
                attrs = st.get("attributes") or {}
                row = {
                    "instance_id": inst["id"], "instance": inst["name"],
                    "entity_id": eid, "name": fname or eid, "state": st.get("state"),
                    "domain": dom, "exposed": is_exposed,
                }
                # Extra attributes the guided HA-action widgets need (select options,
                # number bounds). Only for the controllable domains, to keep rows small.
                if dom in ("select", "input_select") and isinstance(attrs.get("options"), list):
                    row["options"] = attrs["options"]
                if dom in ("number", "input_number"):
                    for k in ("min", "max", "step"):
                        if attrs.get(k) is not None:
                            row[k] = attrs[k]
                rows.append(row)
    return {"entities": rows, "total": total, "returned": len(rows),
            "total_all": sum(domains.values()),
            "domains": sorted(domains), "domain_counts": domains,
            "exposed_count": exposed_count, "topics": list(TOPICS),
            "errors": errors}


def redact(row: dict) -> dict:
    """An instance row safe to return: reports whether a token is set, never what."""
    out = {k: v for k, v in row.items() if k != "token"}
    out["has_token"] = bool(row.get("token"))
    out["is_default"] = bool(row.get("is_default"))
    out["enabled"] = bool(row.get("enabled"))
    return out


def call_service(base_url: str, token: str | None, domain: str, service: str,
                 data: dict | None = None) -> dict[str, Any]:
    """Call any Home Assistant service (``domain.service``) with a data payload.

    The scheduler's HA actions use this for non-notify automations (switch.turn_on,
    climate.set_temperature, scene.turn_on, …). Never raises — the result IS the answer.
    """
    if not token:
        return {"ok": False, "error": "no token configured for this instance"}
    domain = (domain or "").strip().strip("/")
    service = (service or "").strip().strip("/")
    if not domain or not service:
        return {"ok": False, "error": "domain and service are required"}
    payload = json.dumps(data or {}).encode()
    url = base_url.rstrip("/") + f"/api/services/{domain}/{service}"
    req = urllib.request.Request(url, data=payload, headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            return {"ok": 200 <= resp.status < 300, "status": resp.status}
    except urllib.error.HTTPError as e:
        hint = ("bad data or unknown service on this instance" if e.code == 400
                else "token rejected" if e.code in (401, 403)
                else "service/domain not found" if e.code == 404 else f"HTTP {e.code}")
        return {"ok": False, "error": hint}
    except Exception as e:                                       # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def send_notification(base_url: str, token: str | None, service: str,
                      title: str, message: str) -> dict[str, Any]:
    """Fire one HA ``notify.*`` service. Never raises — the result IS the answer.

    ``service`` may be given with or without the ``notify.`` prefix; both forms turn
    up in the wild and rejecting one would be a pointless trap.
    """
    name = service.split(".", 1)[1] if service.startswith("notify.") else service
    payload = json.dumps({"title": title, "message": message}).encode()
    url = base_url.rstrip("/") + f"/api/services/notify/{name}"
    req = urllib.request.Request(url, data=payload, headers={
        "Authorization": f"Bearer {token}" if token else "",
        "Content-Type": "application/json",
    }, method="POST")
    if not token:
        return {"ok": False, "error": "no token configured for this instance"}
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            return {"ok": 200 <= resp.status < 300, "status": resp.status}
    except urllib.error.HTTPError as e:
        # 400 here usually means the service does not exist on that instance.
        hint = ("no such notify service on this instance" if e.code == 400
                else "token rejected" if e.code in (401, 403) else f"HTTP {e.code}")
        return {"ok": False, "error": hint}
    except Exception as e:                                       # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
