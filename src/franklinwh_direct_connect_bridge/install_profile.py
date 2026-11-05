"""The install profile in plain words (#496) — one card per gateway, pure, no I/O.

What the gateway reports is shown as a fact with where it came from, for the user to
confirm. Only what the local API can't tell is asked: what the battery backs up, DC-coupled
solar on an aPower S, the battery's name, and the aPower model only when its PE_HW_VER code
isn't in the catalogue. Answers are System
Setup overrides (:mod:`system_setup`); confirmations are kept apart from them so a
confirmed value is still re-read from the gateway.
"""
from __future__ import annotations

import time
from typing import Any

UNREAD = "Couldn't be read"

_SOLAR = {"ac": "AC-coupled solar", "dc": "DC-coupled solar (aPower S)",
          "remote": "Remote solar"}


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def _models_read(v: dict) -> list[str] | None:
    """Each aPower's model, read from its PE_HW_VER code — None unless every one is known."""
    models = v.get("_apower_models")
    return models if models and all(models) else None


def _batteries(v: dict, count: Any) -> str:
    models = _models_read(v)
    if models:
        seen: dict[str, int] = {}
        for m in models:
            seen[m] = seen.get(m, 0) + 1
        return ", ".join(f"{n} {m}" for m, n in seen.items())
    return _plural(count, "aPower") if isinstance(count, int) else UNREAD


def _facts(info: dict, v: dict, modes: list[str], off_grid: bool | None) -> list[dict]:
    src = v.get("_sources") or {}
    model, country, count = info.get("model"), info.get("country"), info.get("apower_count")
    solar_kind = v.get("solar_type") or "none"
    kwp = v.get("solar_kwp") or 0
    if solar_kind == "none":
        solar = "No solar"
    else:
        solar = _SOLAR.get(solar_kind, solar_kind) + (f", {kwp:g} kW" if kwp else "")
    if v.get("_overridden", {}).get("solar_type") or v.get("_overridden", {}).get("solar_kwp"):
        solar_src = "Your answer"
    else:
        solar_src = src.get("solar") or "Not read yet: the gateway hasn't answered"
    gen_src = ("Your answer" if v.get("_overridden", {}).get("generator_input")
               else src.get("generator_input") or "Not read yet: the gateway hasn't answered")
    sc_src = src.get("load_shedding") or "Not read yet: the gateway hasn't answered"
    n_sc = info.get("circuit_count")
    return [
        {"key": "gateway", "label": "Gateway",
         "value": (f"{model} ({country})" if model and country else model or UNREAD),
         "source": "Read from the gateway's hardware id"},
        {"key": "batteries", "label": "Batteries", "value": _batteries(v, count),
         "source": src.get("apower") or "Read from the gateway's list of aPowers"},
        {"key": "grid", "label": "Grid",
         "value": (UNREAD if off_grid is None
                   else "Off-grid right now" if off_grid else "Connected to the grid"),
         "source": "Read from the gateway's grid switch and off-grid state"},
        {"key": "modes", "label": "Operating modes",
         "value": ", ".join(modes) if modes else UNREAD,
         "source": "Read from the gateway's list of modes"},
        {"key": "solar", "label": "Solar", "value": solar, "source": solar_src},
        {"key": "generator", "label": "Generator",
         "value": "Installed" if v.get("generator_input") else "Not installed",
         "source": gen_src},
        {"key": "smart_circuits", "label": "Smart Circuits (load shedding)",
         "value": ((_plural(n_sc, "circuit") if isinstance(n_sc, int) and n_sc else "Installed")
                   if v.get("load_shedding") else "None"),
         "source": sc_src},
        {"key": "v2l", "label": "Vehicle-to-Load (V2L)",
         "value": "Installed" if v.get("v2l") else "Not installed",
         "source": src.get("v2l") or "Not read yet: the gateway hasn't answered"},
    ]


def _questions(v: dict, models: list[str]) -> list[dict]:
    ov = v.get("_overridden") or {}
    out = [] if _models_read(v) else [
        {"key": "apower_model", "label": "Which aPower model?",
         "help": "The gateway's model code isn't in the catalogue; it sets the battery capacity.",
         "options": [{"value": m, "label": m} for m in models],
         "value": v.get("apower_model") or "", "answered": bool(v.get("apower_model"))}]
    out += [
        {"key": "backup", "label": "What does the battery back up?",
         "help": "The gateway can't tell how the backup was wired.",
         "options": [{"value": "whole", "label": "The whole home"},
                     {"value": "panel", "label": "Only a backup-loads panel"}],
         "value": "whole" if v.get("whole_home_backup") else "panel",
         "answered": bool(ov.get("whole_home_backup"))},
    ]
    if v.get("apower_model") == "aPower S":
        out.append({"key": "solar_dc", "label": "Is solar wired into the aPower S (DC, MPPT)?",
                    "help": "The gateway can't see solar connected to an aPower S.",
                    "options": [{"value": True, "label": "Yes"}, {"value": False, "label": "No"}],
                    "value": v.get("solar_type") == "dc",
                    "answered": bool(ov.get("solar_type"))})
    out.append({"key": "battery_label", "label": "Battery name (optional)",
                "help": "Shown in notifications and Home Assistant.",
                "options": [], "value": v.get("battery_label") or "",
                "answered": bool(ov.get("battery_label"))})
    return out


def _seen(h: dict | None, what: str) -> str:
    """"Your history: …" for one path's stored samples, or "" when it never carried power."""
    if not h:
        return ""
    day = time.strftime("%Y-%m-%d", time.localtime(h["last_ts"]))
    return f"Your history: {what} up to {h['peak_w'] / 1000:.1f} kW, most recently {day}"


def _with_history(facts: list[dict], history: dict | None) -> None:
    """History is evidence (#496): power that has flowed through a path proves it exists."""
    h = history or {}
    by = {f["key"]: f for f in facts}
    lines = {"solar": _seen(h.get("solar"), "solar"),
             "generator": _seen(h.get("generator"), "generator power"),
             "grid": _seen(h.get("grid"), "power through the grid connection")}
    for key, line in lines.items():
        if line:
            by[key]["source"] = f"{by[key]['source']}. {line}"
    if h.get("generator") and by["generator"]["value"] == "Not installed":
        by["generator"]["value"] = "Installed"
    if h.get("solar") and by["solar"]["value"] == "No solar":
        # e.g. DC solar on an aPower S, which the aGate's PV settings don't cover.
        by["solar"]["value"] = "Solar seen in your history"
        by["solar"]["source"] = (lines["solar"] + "; not in the gateway's PV settings")


def card(gateway_id: str, name: str, info: dict, values: dict, *, modes: list[str],
         off_grid: bool | None, models: list[str] | None = None,
         history: dict | None = None) -> dict[str, Any]:
    """One gateway's card: facts to confirm, then questions. ``history`` is
    :meth:`MetricsStore.power_history` for this gateway."""
    from .devicedb import APOWER_SPECS
    confirmed = values.get("_confirmed") or {}
    facts = _facts(info or {}, values, modes, off_grid)
    _with_history(facts, history)
    for f in facts:
        # Confirmed only while it still reads the same: a change asks again.
        f["confirmed"] = f["value"] != UNREAD and confirmed.get(f["key"]) == f["value"]
    return {"gateway_id": gateway_id, "name": name, "facts": facts,
            "questions": _questions(values, models or list(APOWER_SPECS))}


def answer_updates(key: str, value: Any) -> dict[str, Any]:
    """The System Setup fields one answer sets."""
    if key == "backup":
        whole = value == "whole"
        return {"whole_home_backup": whole, "non_backup_loads": not whole}
    if key == "solar_dc":
        # "No" reverts to what the gateway reports.
        return {"solar_type": "dc" if value else None}
    if key in ("apower_model", "battery_label"):
        return {key: value}
    raise ValueError(f"unknown question: {key}")


_SHORT = {"apower_model": "aPower model", "backup": "backup", "solar_dc": "DC solar",
          "battery_label": "battery name"}


def summary(card: dict) -> list[str]:
    """The card as a few support-info lines (owner, 2026-11-06): what's installed, the
    modes, the answers, and how much has been confirmed."""
    f = {x["key"]: x["value"] for x in card["facts"]}
    install = [f["gateway"], f["batteries"], f["grid"], f["solar"],
               f"generator {f['generator']}", f"Smart Circuits {f['smart_circuits']}",
               f"V2L {f['v2l']}"]
    answers = []
    for q in card["questions"]:
        label = next((o["label"] for o in q["options"] if o["value"] == q["value"]), q["value"])
        if not q["answered"] and q["key"] != "battery_label":
            label = "not answered"
        answers.append(f"{_SHORT.get(q['key'], q['key'])} {label}")
    done = sum(1 for x in card["facts"] if x["confirmed"])
    return ["install: " + " · ".join(install),
            "modes: " + f["modes"],
            "answers: " + " · ".join(answers),
            f"checked: {done} of {len(card['facts'])} confirmed"]
