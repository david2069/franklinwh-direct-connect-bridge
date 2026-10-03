"""Generator view-model from cmdType 1901 — pure, no I/O.

1901 carries three loosely-related groups and the tab must not blur them:

1. **Generator** — enable flag, model, rated power, run state, SoC start/stop
   thresholds, maintenance-exercise schedule.
2. **Operating windows** (``charge1..3``) — FranklinWH's Generator support page
   states the generator supports *"up to 3 non-overlapping operating periods
   (00:00-23:59) with minimum 1-minute intervals"*, which matches this trio
   exactly, so they are the generator's schedule — not the grid-charge windows the
   catalog guessed at. Caveat: on the observed gateway window 1 is enabled
   (11:00-23:59) while **no generator is installed**, so a stored value here does
   not imply an active schedule.
3. **Shared trailing electricals** (``power``/``curr``/``volt``/``freq``) — these
   appear byte-identically in the 1411 smart-circuit meter payload, so they are
   gateway-level, **not** generator output. ``volt: 2`` is meaningless as a
   generator voltage. Only ``genpowerGen`` is treated as generator power.
"""

from __future__ import annotations

from typing import Any

#: ``genStat`` — matches franklinwh_cloud.const.states.GENERATOR_STATE.
STATE = {0: "Standby / OFF", 1: "Running / ON", 2: "Cooldown", 3: "Fault"}

#: ``manuSw``. The cloud documents only 1 and 2; 0 is observed on hardware with no
#: generator installed and is reported as unset rather than guessed at.
MODE = {0: "Unset", 1: "Auto-schedule", 2: "Manual"}

MODE_TO_VALUE = {"auto": 1, "manual": 2}


def enabled(payload: dict) -> bool:
    """Is the generator feature turned ON (``genEn``)?

    Distinct from physically installed. The official mobile app lets you enable the
    feature on a gateway with no module wired up — and so does the local protocol —
    so this is the flag that gates configuration, not a hardware fact.
    """
    return bool(payload.get("genEn"))


def configured(payload: dict) -> bool:
    """Is there evidence of real generator hardware behind the feature flag?

    A model string, a rated power or a non-idle run state. None of these can be
    faked by the enable flag alone, so this is the closest the protocol gets to
    "something is actually wired up" — and it is still only evidence: there is no
    accessory serial or firmware version anywhere in the local protocol.
    """
    return bool(
        (payload.get("genModel") or "").strip()
        or payload.get("genRatedPower")
        or payload.get("genStat")
    )


def installed(payload: dict) -> bool:
    """Enabled OR showing hardware evidence. Kept as the broad "show me something"
    signal; use :func:`enabled` to decide whether configuration may be edited."""
    return enabled(payload) or configured(payload)


def _window(payload: dict, n: int) -> dict[str, Any]:
    return {
        "index": n,
        "enabled": bool(payload.get(f"charge{n}En")),
        "start": payload.get(f"charge{n}StartTime") or None,
        "end": payload.get(f"charge{n}EndTime") or None,
    }


def build(payload: dict) -> dict[str, Any]:
    """Assemble the ``/api/generator`` view-model."""
    p = payload or {}
    stat = p.get("genStat", 0)
    mode = p.get("manuSw", 0)

    return {
        "installed": installed(p),
        "enabled": enabled(p),
        "configured": configured(p),
        # Editing generator config is pointless — and misleading — while the feature
        # is off. The gateway accepts the writes either way (verified 2026-09-14),
        # which is exactly why the UI must not imply they do something.
        "editable": enabled(p),
        "state": stat,
        "state_name": STATE.get(stat, f"Unknown ({stat})"),
        "running": stat == 1,
        "fault": stat == 3,
        "mode": mode,
        "mode_name": MODE.get(mode, f"Unknown ({mode})"),
        "model": (p.get("genModel") or "").strip() or None,
        "rated_power_w": p.get("genRatedPower") or None,
        # Generator output. The generic power/curr/volt/freq keys are excluded on
        # purpose — see the module docstring.
        "power_w": p.get("genpowerGen"),
        "soc_start_pct": p.get("genStartElec"),
        "soc_stop_pct": p.get("genCloseElec"),
        "start_delay_s": p.get("startDelTime"),
        "optimal_power_pct": p.get("genOptiPPoint"),
        "grid_volt_check": p.get("gridVoltCheck"),
        "maintenance": {
            "enabled": bool(p.get("oilmanoEn")),
            "every_days": p.get("manoFre"),
            "day": p.get("manoDate"),
            "start": (p.get("manoStartTime") or "").strip() or None,
            "run_minutes": p.get("manoTime"),
            "manual_exit": bool(p.get("manoManExit")),
        },
        # Kept under the old key as well so existing callers do not break.
        "operating_windows": [_window(p, n) for n in (1, 2, 3)],
        "charge_windows": [_window(p, n) for n in (1, 2, 3)],
    }
