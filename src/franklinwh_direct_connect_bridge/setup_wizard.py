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

#: How many aGates and aPowers the owner says they have. Asked, not derived: before
#: anything is discovered there is nothing to derive FROM, and the answer tells the wizard
#: what it should expect to find. Both default to 1 — the overwhelmingly common case, and a
#: default that is wrong is cheap to correct here and expensive to discover later.
EXPECTED_AGATES_KEY = "setup_expected_agates"
EXPECTED_APOWERS_KEY = "setup_expected_apowers"
DEFAULT_EXPECTED = 1
#: One site, sanity bounds. Not a product limit — a guard against a typo becoming a scan.
MAX_EXPECTED = 16

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


def expected(store) -> dict[str, int]:
    """How many aGates and aPowers the owner says are installed. Defaults to 1 each."""
    def _one(key: str) -> int:
        raw = (store.get_config(key, "") if store is not None else "") or ""
        try:
            n = int(raw)
        except (TypeError, ValueError):
            return DEFAULT_EXPECTED
        return n if 1 <= n <= MAX_EXPECTED else DEFAULT_EXPECTED

    return {"agates": _one(EXPECTED_AGATES_KEY), "apowers": _one(EXPECTED_APOWERS_KEY)}


def set_expected(store, *, agates: int | None = None, apowers: int | None = None) -> dict[str, int]:
    """Record the counts. Out-of-range is refused rather than clamped: silently storing
    something other than what was typed is how a wrong number survives unnoticed."""
    for name, val in (("agates", agates), ("apowers", apowers)):
        if val is None:
            continue
        if not isinstance(val, int) or isinstance(val, bool) or not (1 <= val <= MAX_EXPECTED):
            raise ValueError(f"{name} must be a whole number from 1 to {MAX_EXPECTED}")
    if store is not None:
        if agates is not None:
            store.set_config(EXPECTED_AGATES_KEY, str(agates))
        if apowers is not None:
            store.set_config(EXPECTED_APOWERS_KEY, str(apowers))
    return expected(store)


def _expected_step(exp: dict[str, int], gateways: list, apowers_found: int | None) -> dict[str, Any]:
    """What the owner says they have, against what has been found so far.

    This is the one step that is ASKED rather than derived, because at first run there is
    nothing to derive from. Its value is the comparison: it turns "1 gateway configured"
    into "1 of the 2 you said you have", which is the difference between a wizard that
    looks finished and one that is.
    """
    real = [g for g in gateways if not getattr(g, "is_mock", False)]
    found_gw = len(real)
    short_gw = max(0, exp["agates"] - found_gw)
    short_ap = (max(0, exp["apowers"] - apowers_found)
                if apowers_found is not None else None)
    bits = [f"{found_gw} of {exp['agates']} aGate(s) configured"]
    if apowers_found is not None:
        bits.append(f"{apowers_found} of {exp['apowers']} aPower(s) reporting")
    return {
        "id": "expected",
        "title": "How much hardware do you have?",
        "required": True,
        # Satisfied once what was found matches what was declared. Finding MORE is fine —
        # it means the declaration was low, not that setup is incomplete.
        "satisfied": short_gw == 0 and (short_ap in (0, None)),
        "detail": " · ".join(bits),
        "values": {"agates": exp["agates"], "apowers": exp["apowers"]},
        "found": {"agates": found_gw, "apowers": apowers_found},
        "defaults": {"agates": DEFAULT_EXPECTED, "apowers": DEFAULT_EXPECTED},
        "max": MAX_EXPECTED,
        "action": "expected",
    }


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


def steps(*, store, gateways: list, profile_values: dict[str, Any],
          ha_configured: bool, notifications_configured: bool,
          tariff_configured: bool,
          apowers_found: int | None = None) -> list[dict[str, Any]]:
    """Every step with its current state, so a re-run shows reality, not blank fields."""
    return [
        _expected_step(expected(store), gateways, apowers_found),
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
    sts = steps(store=store, **kw)
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
