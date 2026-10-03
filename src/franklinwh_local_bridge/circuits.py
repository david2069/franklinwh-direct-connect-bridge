"""Smart-circuit presence detection and view-model — pure, no I/O.

Two independent facts get conflated easily, and the cloud library conflates them
(see franklinwh-cloud#7):

* **How many circuits the region supports** — 3 on US, 2 on AU.
* **Whether a smart-circuit enclosure is installed at all** — plenty of systems
  have none, and the gateway reports the ``Sw1``–``Sw3`` blocks regardless.

The firmware always returns three ``Sw{n}*`` blocks. On a 2-circuit AU gateway the
third is filled with factory defaults — a placeholder name, ``SocLowSet: 20`` and a
schedule of ``"2000-01-01 00:00"``. So **key presence proves nothing**, and neither
does key absence: this module reports evidence and a verdict, and never silently
drops a circuit from the payload.

``CarSW`` is deliberately *not* treated as circuit 3. The cloud docs say the CarSW
port is ``Sw3`` in cmdType 311, but the local 1409 payload carries ``CarSwConsSup*``
as separate top-level fields alongside a full ``Sw3`` block — locally they are
distinct. It is surfaced as its own channel instead of being folded into a circuit.
"""

from __future__ import annotations

from typing import Any

MAX_CIRCUITS = 3

#: A schedule slot the firmware has never had written to it.
_PLACEHOLDER_PREFIXES = ("2000-01-01", "1970-01-01")

#: ``auto`` resolves by evidence; an integer pins the count (0 = none installed).
COUNT_CHOICES = ("auto", "0", "2", "3")


def _is_placeholder(slot: Any) -> bool:
    if not isinstance(slot, str) or not slot.strip():
        return True
    return slot.startswith(_PLACEHOLDER_PREFIXES)


def schedule_slots(cfg: dict, cid: int) -> list[dict[str, Any]]:
    """The four schedule slots for one circuit, as on/off pairs.

    ``SwXTime`` holds four datetimes as V2 strings; ``SwXTimeEn`` enables a slot and
    ``SwXTimeSet`` pairs them (observed ``[1,0,1,0]`` — slot 0 opens, slot 1 closes).
    """
    times = cfg.get(f"Sw{cid}Time") or []
    enabled = cfg.get(f"Sw{cid}TimeEn") or []
    kinds = cfg.get(f"Sw{cid}TimeSet") or []
    slots = []
    for i in range(len(times)):
        slots.append({
            "index": i,
            "at": times[i] if not _is_placeholder(times[i]) else None,
            "enabled": bool(enabled[i]) if i < len(enabled) else False,
            "action": ("on" if kinds[i] else "off") if i < len(kinds) else None,
        })
    return slots


def meter(meter_payload: dict | None, cid: int) -> dict[str, Any]:
    """Per-circuit electricals from 1411.

    Only circuits 1 and 2 have meter channels in the observed payload — there is no
    ``SW3*`` group. Whether a US 3-circuit unit exposes one is unverified, so a
    missing group yields ``None`` rather than ``0``: absent data must not read as a
    real zero.

    Scaling: ``freq: 499`` → 49.9 Hz confirms a ÷10 factor, applied to volts here.
    The observed ``Sw1Volt: 1020`` → 102.0 V does not match AU 230 V mains, but both
    circuits were off at capture; see ``docs/SMART_CIRCUITS_DESIGN.md`` §6.
    """
    p = meter_payload or {}
    volt = p.get(f"Sw{cid}Volt")
    curr = p.get(f"SW{cid}Curr")
    power = p.get(f"SW{cid}ExpPower")
    energy = p.get(f"SW{cid}ExpEnergy")
    return {
        "volts": round(volt / 10, 1) if isinstance(volt, (int, float)) else None,
        "amps": curr if isinstance(curr, (int, float)) else None,
        "watts": power if isinstance(power, (int, float)) else None,
        # Lifetime counter, not "today" — a daily figure must be differenced by the
        # bridge across midnight (FEAT-SMART-CIRCUITS phase 2).
        "energy_lifetime_kwh": (energy / 100 if isinstance(energy, (int, float)) else None),
        "has_meter": volt is not None or curr is not None,
    }


def carsw(meter_payload: dict | None, cfg: dict | None = None) -> dict[str, Any]:
    """The ``CarSW`` channel — reported separately, never folded into circuit 3."""
    p, c = meter_payload or {}, cfg or {}
    exp, imp = p.get("CarSWExpEnergy"), p.get("CarSWImpEnergy")
    return {
        "amps": p.get("CarSWCurr"),
        "watts": p.get("CarSWPower"),
        "export_lifetime_kwh": exp / 100 if isinstance(exp, (int, float)) else None,
        "import_lifetime_kwh": imp / 100 if isinstance(imp, (int, float)) else None,
        "enabled": bool(c.get("CarSwConsSupEnable")),
    }


def evaluate(cfg: dict, meter_payload: dict | None, cid: int) -> dict[str, Any]:
    """Evidence for/against circuit ``cid`` physically existing.

    Returns ``present`` as ``True``/``False``/``None`` (unknown) with the reasons, so
    the UI can say *why* a circuit is missing instead of just hiding it.
    """
    for_, against = [], []

    m = meter(meter_payload, cid)
    if m["watts"] or m["amps"] or m["volts"]:
        for_.append("live metering")
    if m["energy_lifetime_kwh"]:
        for_.append("lifetime energy recorded")

    if cfg.get(f"Sw{cid}Mode") == 1:
        for_.append("circuit is on")

    slots = schedule_slots(cfg, cid)
    if any(s["at"] for s in slots):
        for_.append("schedule configured")
    elif slots:
        against.append("schedule is factory placeholder")

    if not m["has_meter"]:
        against.append("no meter channel in 1411")

    if for_:
        present: bool | None = True
    elif against:
        # Never-used-but-installed looks identical to absent from the payload alone,
        # so a purely negative case is unknown, not a confident False.
        present = False if len(against) > 1 else None
    else:
        present = None

    return {"present": present, "evidence_for": for_, "evidence_against": against}


def build(cfg: dict, meter_payload: dict | None = None,
          override: str = "auto", expected: int | None = None) -> dict[str, Any]:
    """Assemble the ``/api/circuits`` view-model.

    ``override`` pins the count (``"0"``/``"2"``/``"3"``) or ``"auto"`` to detect.
    ``expected`` is the gateway model's channel count from :mod:`devicedb` — a strong
    prior that RULES OUT channels the hardware cannot have, but never rules one IN:
    a model supporting three circuits may have no enclosure fitted. So the model can
    turn a detected ``True`` into ``False``, and can settle an ``unknown``, but it
    cannot manufacture a circuit that shows no evidence of existing.

    All three circuits are always returned; ``present`` and ``source`` say which are
    real and how that was decided.
    """
    pinned: int | None = None
    if override not in ("auto", "", None):
        try:
            pinned = max(0, min(MAX_CIRCUITS, int(override)))
        except (TypeError, ValueError):
            pinned = None

    out = []
    for cid in range(1, MAX_CIRCUITS + 1):
        verdict = evaluate(cfg, meter_payload, cid)
        source = "detected"
        if pinned is None and expected is not None and cid > expected:
            # The model says this channel does not exist. Trust it over weak
            # positive evidence, but record that it was the model's call.
            if verdict["present"] is not False:
                verdict = {**verdict,
                           "present": False,
                           "evidence_against": verdict["evidence_against"]
                           + [f"gateway model has {expected} circuits"]}
            source = "model"
        if pinned is not None:
            verdict = {**verdict, "present": cid <= pinned}
        out.append({
            "id": cid,
            "name": cfg.get(f"Sw{cid}Name") or f"Circuit {cid}",
            "on": cfg.get(f"Sw{cid}Mode") == 1,
            "mode": cfg.get(f"Sw{cid}Mode", 0),
            "pro_load": cfg.get(f"Sw{cid}ProLoad", 0),
            "soc_cutoff": {
                "enabled": bool(cfg.get(f"Sw{cid}AtuoEn")),   # [sic] vendor typo
                "soc": cfg.get(f"Sw{cid}SocLowSet", 0),
            },
            "schedule": schedule_slots(cfg, cid),
            **meter(meter_payload, cid),
            **verdict,
            "source": "setting" if pinned is not None else source,
        })

    detected = [c for c in out if c["present"]]
    overall = ("setting" if pinned is not None
               else "model+detected" if expected is not None else "detected")
    return {
        "circuits": out,
        "count": len(detected),
        "expected_circuits": expected,
        "source": overall,
        # Distinct from "this region has fewer circuits": nothing is installed.
        "installed": bool(detected) if pinned is None else pinned > 0,
        "merge": bool(cfg.get("SwMerge")),   # US-only: circuits merged across aGates
        "carsw": carsw(meter_payload, cfg),
    }


# ── schedule writing ─────────────────────────────────────────────────────────
# The four slots are two on/off PAIRS (TimeSet [1,0,1,0] — slot 0 opens, slot 1
# closes, slot 2 opens, slot 3 closes). FranklinWH's own Smart Circuits page
# describes scheduling as "Customize the time period ... to automatically turn the
# circuit on or off", which matches that pairing.
#
# Each slot's value is a full datetime ("2026-06-19 16:02") even though the schedule
# is recurring — the date appears to be when the slot was written, not a one-shot
# date, since a schedule dated months ago still reports as active. That is NOT
# confirmed, so an edit PRESERVES the existing date component and changes only the
# time; it never invents a new date, and never silently converts a slot to one-shot.

class ScheduleError(ValueError):
    """Rejected schedule — the firmware would accept nonsense, so we do not."""


def _hhmm(value: str) -> tuple[int, int]:
    try:
        h, m = str(value).strip().split(":")
        hh, mm = int(h), int(m)
    except (ValueError, AttributeError):
        raise ScheduleError(f"time must be HH:MM, got {value!r}")
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        raise ScheduleError(f"time out of range: {value!r}")
    return hh, mm


def _date_part(existing: Any, fallback: str) -> str:
    if isinstance(existing, str) and " " in existing:
        head = existing.split(" ", 1)[0]
        if not head.startswith(_PLACEHOLDER_PREFIXES):
            return head
    return fallback


def build_schedule_write(cfg: dict, cid: int, windows: list[dict],
                         today: str) -> dict[str, Any]:
    """Return the patched ``Sw{cid}*`` schedule fields for a 1409 full-block write.

    ``windows`` is up to two ``{enabled, start, end}`` entries with ``HH:MM`` times.
    ``today`` supplies the date for a slot that has never been written.

    Validation the firmware does not do: an end at or before its start is rejected,
    and two enabled windows may not overlap.
    """
    if len(windows) > 2:
        raise ScheduleError("a circuit supports at most two on/off windows")

    times = list(cfg.get(f"Sw{cid}Time") or [""] * 4)
    times += [""] * (4 - len(times))
    enabled = [0, 0, 0, 0]
    spans = []

    for i, w in enumerate(windows):
        on = bool(w.get("enabled"))
        sh, sm = _hhmm(w.get("start"))
        eh, em = _hhmm(w.get("end"))
        start_min, end_min = sh * 60 + sm, eh * 60 + em
        if end_min <= start_min:
            raise ScheduleError(
                f"window {i + 1}: end {w.get('end')} is not after start {w.get('start')}")
        if on:
            for other_i, (os_, oe) in spans:
                if start_min < oe and os_ < end_min:
                    raise ScheduleError(
                        f"window {i + 1} overlaps window {other_i + 1}")
            spans.append((i, (start_min, end_min)))

        a, b = i * 2, i * 2 + 1
        times[a] = f"{_date_part(times[a], today)} {sh:02d}:{sm:02d}"
        times[b] = f"{_date_part(times[b], today)} {eh:02d}:{em:02d}"
        enabled[a] = enabled[b] = 1 if on else 0

    return {
        f"Sw{cid}Time": times,
        f"Sw{cid}TimeEn": enabled,
        # Pairing is fixed: open, close, open, close.
        f"Sw{cid}TimeSet": [1, 0, 1, 0],
    }
