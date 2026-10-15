"""First-run setup, and re-configuration later.

The point of difference, from `BACKLOG.md` → FEAT-SETUP-WIZARD: the Direct Connect API
exposes what is actually installed, so this **derives first and asks second**. It confirms
what was found rather than interrogating the user — a different interaction from a wizard
built on an API that cannot see the installation.

Three rules the backlog settles, implemented here rather than re-decided:

* **Derived-but-wrong must be correctable.** Every derived value is offered as a default the
  user can overwrite, and an explicit override wins. A wizard that cannot be contradicted is
  worse than no wizard when the derivation is wrong.
* **Re-runnable, and that is the harder case.** Each step reports whether it is already
  satisfied, so a second pass shows current state instead of blank fields, and nothing is
  silently overwritten.
* **Capability gating is not permission gating.** This module answers "is this installed",
  never "may this user see it". Role-based hiding is FEAT-USERS-RBAC and must stay separate.
"""
from __future__ import annotations

from typing import Any

#: Stored in the config table. Absent ⇒ never run ⇒ offer the wizard.
STATE_KEY = "setup_wizard_state"

#: ``pending`` never completed · ``done`` finished · ``skipped`` user declined.
STATES = ("pending", "done", "skipped")

#: Optional subsystems. Every one of these must be skippable: a wizard that implies
#: everything is mandatory is why people abandon them.
OPTIONAL_STEPS = ("home_assistant", "notifications", "billing")


def state(store) -> str:
    """Where the wizard stands. ``pending`` when it has never been completed."""
    if store is None:
        return "pending"
    val = store.get_config(STATE_KEY, "") or ""
    return val if val in STATES else "pending"


def set_state(store, value: str) -> str:
    if value not in STATES:
        raise ValueError(f"unknown wizard state {value!r}; expected one of {STATES}")
    if store is not None:
        store.set_config(STATE_KEY, value)
    return value


def _gateway_step(gateways: list) -> dict[str, Any]:
    real = [g for g in gateways if not getattr(g, "is_mock", False)]
    return {
        "id": "gateway",
        "title": "Find your aGate",
        "required": True,
        "satisfied": bool(real),
        "detail": (f"{len(real)} gateway(s) configured" if real else
                   "No real gateway yet — Discover scans the LAN, or enter the IP."),
        "action": "scan",
    }


def _profile_step(values: dict[str, Any]) -> dict[str, Any]:
    """What the gateway says is installed. Derived, and every field overridable.

    ``_derived`` lists what came from the device; anything outside it is a default or an
    override, and the UI must not present a default as a measurement.
    """
    derived = values.get("_derived") or {}
    overridden = values.get("_overridden") or {}
    facts = {k: v for k, v in values.items() if not k.startswith("_")}
    return {
        "id": "profile",
        "title": "Confirm what's installed",
        "required": True,
        "satisfied": bool(derived),
        "detail": ("Read from the gateway — change anything that is wrong."
                   if derived else "Could not read the install profile from the gateway."),
        "values": facts,
        "derived": sorted(derived),
        "overridden": sorted(k for k, v in overridden.items() if v),
        "action": "profile",
    }


def _optional_step(step_id: str, title: str, satisfied: bool, detail: str) -> dict[str, Any]:
    return {
        "id": step_id, "title": title, "required": False, "satisfied": satisfied,
        "detail": detail, "skippable": True,
        "note": "You can set this up later.",
    }


def capability_tabs(values: dict[str, Any], *, generator_installed: bool) -> dict[str, bool]:
    """Which capability-gated tabs apply to THIS site.

    Generalises the one rule that already existed — the Generator tab hidden when no
    generator — rather than inventing a second mechanism. ``True`` means *this site has it*;
    it says nothing about whether a given user may see it.
    """
    facts = {k: v for k, v in (values or {}).items() if not k.startswith("_")}
    solar = bool(facts.get("solar_kwp") or facts.get("solar_type"))
    return {
        "generator": bool(generator_installed or facts.get("generator_input")),
        "solar": solar,
        "circuits": bool(facts.get("load_shedding")),
    }


def steps(*, gateways: list, profile_values: dict[str, Any],
          ha_configured: bool, notifications_configured: bool,
          tariff_configured: bool) -> list[dict[str, Any]]:
    """Every step with its current state, so a re-run shows reality, not blank fields."""
    return [
        _gateway_step(gateways),
        _profile_step(profile_values or {}),
        _optional_step("home_assistant", "Home Assistant", ha_configured,
                       "Publish the battery as Home Assistant entities over MQTT."),
        _optional_step("notifications", "Notifications", notifications_configured,
                       "Be told when something happens — outages, dispatch, errors."),
        _optional_step("billing", "Tariffs & costs", tariff_configured,
                       "Energy prices, so the Costs tab and tariff conditions work."),
    ]


def summary(store, **kw) -> dict[str, Any]:
    """The wizard's whole state in one read."""
    st = state(store)
    sts = steps(**kw)
    required_done = all(s["satisfied"] for s in sts if s["required"])
    return {
        "state": st,
        "complete": st == "done",
        "required_satisfied": required_done,
        # Offer it when it has never been finished AND something required is still missing.
        # Re-running is always allowed; this is only about whether we PROMPT.
        "should_prompt": st == "pending" and not required_done,
        "steps": sts,
    }
