"""Solar view-model — pure, no I/O.

Everything solar is scattered across 1903 (config + relays) and 1301 (live flow), and
the field naming is inconsistent even within one payload:

* ``installPV1port`` / ``installPV2port`` but ``PV1RatedPower`` / ``PV2RatedPower``
* ``solarRelayStat`` (no index) beside ``loadRelay1Stat`` / ``loadRelay2Stat``
* ``loadSolar1RatedPower`` / ``loadSolar2RatedPower`` beside a bare
  ``mainsSolarRatedPower``
* ``solarPower`` is live power in **deciwatts**, duplicating ``p_sun`` in watts —
  measured 2026-09-14: ``solarPower 21810`` with ``p_sun 2181``, and ``21310`` / ``2131``
  45 s later. Exactly ×10 twice. (It is *not* cumulative energy — an early guess that
  the numbers happened to fit, and a second sample killed.)
* ``solarPowerGen`` held 224 across both samples while power moved, so it is config of
  some kind, **not** live generation. Left undecoded rather than labelled wrongly.

This module's whole job is to group those into sections a human can read, which the
generic Live Points view cannot do because it keys off the raw names.
"""

from __future__ import annotations

from typing import Any

#: ``PVnRatedPower`` is in units of 100 W (catalog: observed 66 = 6.6 kW).
_RATED_STEP_W = 100


def _kw(raw: Any) -> float | None:
    return round(raw * _RATED_STEP_W / 1000, 2) if isinstance(raw, (int, float)) and raw else None


def _port(cfg: dict, n: int) -> dict[str, Any]:
    """One aGate AC-solar input. Note the inconsistent key casing — deliberate."""
    return {
        "port": n,
        "installed": bool(cfg.get(f"installPV{n}port")),
        "rated_kw": _kw(cfg.get(f"PV{n}RatedPower")),
        "raw_rated": cfg.get(f"PV{n}RatedPower"),
    }


def _relay(value: Any) -> dict[str, Any]:
    """One relay state. ``raw 1`` is **OPEN**, ``raw 0`` is **CLOSED**.

    That is the opposite of the ordinary electrical convention, and it is
    deliberate — FranklinWH uses its own. Two sources agree:

    * the site owner reports solar PV1 and the main grid relay as "OPEN/ON" while
      both are plainly conducting (grid connected, solar producing);
    * FranklinWH's ``AGENT_GROUND_TRUTH.md`` §1 states the encoding outright —
      ``1 = OPEN (connected)`` — and rules *"Do NOT write '1=CLOSED (connected)'
      — this is the wrong way round for this vendor"*.

    The worked examples in that same section say the opposite
    (``solarRelayStat = 1 → CLOSED``), contradicting the rule stated above them
    and the prohibition printed below them. Filed as
    https://github.com/david2069/franklinwh-cloud/issues/8. The rule and the
    hardware agree, so the rule wins.

    ``open`` therefore means energised / conducting here. The raw value travels
    alongside so a reader can always check.
    """
    is_open = bool(value)
    return {
        "open": is_open,
        "state": "open" if is_open else "closed",
        "raw": value,
    }


def build(cfg: dict, flow: dict | None = None,
          run_status: dict | None = None) -> dict[str, Any]:
    """Assemble ``/api/solar`` from 1903 config, 1301 live flow and 1707 relays.

    The hardware has **two separate pairs** of AC solar inputs and the payloads do
    not make that obvious:

    * **Built-in AC PV** — the aGate's own two inputs (``installPV1port`` /
      ``installPV2port``, ``PV1RatedPower`` / ``PV2RatedPower``), whose relays appear
      in 1707 as ``solarRelayStatus`` and — with no shared naming at all —
      ``pvRelay2``.
    * **Remote solar (aPbox)** — a second pair of AC PV inputs
      (``loadSolar1RatedPower`` / ``loadSolar2RatedPower``, counted by
      ``loadSolarAmount``), whose relays are ``loadRelay1Stat`` / ``loadRelay2Stat``,
      alongside the aPbox digital I/O.

    Grouping them by pair is the whole point; the raw names actively obscure it.
    """
    c, f, r = cfg or {}, flow or {}, run_status or {}

    ports = [_port(c, 1), _port(c, 2)]
    p_sun = f.get("p_sun")
    solar_dw = c.get("solarPower")

    # Both report the same quantity; disagreement means one read is stale rather
    # than a real conflict, so surface it instead of silently preferring one.
    derived = solar_dw / 10 if isinstance(solar_dw, (int, float)) else None
    agree = (p_sun is not None and derived is not None
             and abs(derived - p_sun) <= max(50, abs(p_sun) * 0.05))

    # One relay, three names: 1903 solarRelayStat == 1707 solarRelayStatus ==
    # 1301 main_sw[2] (cloud API_COOKBOOK.md:36 documents the last equivalence).
    main_sw = f.get("main_sw") or []
    builtin_relays = [
        _relay(r.get("solarRelayStatus", c.get("solarRelayStat"))),
        _relay(r.get("pvRelay2")),
    ]
    for p, rel in zip(ports, builtin_relays):
        p["relay"] = rel

    return {
        "live": {
            "power_w": p_sun,
            "power_w_from_1903": derived,
            "sources_agree": agree if (p_sun is not None and derived is not None) else None,
            "energy_today_kwh": f.get("kwh_sun"),
        },
        "inputs": {
            "ports": ports,
            "installed_count": sum(1 for p in ports if p["installed"]),
            "total_rated_kw": round(sum(p["rated_kw"] or 0 for p in ports), 2) or None,
            "three_phase_pv": bool(c.get("threePhPvEnb")),
        },
        # aPbox: a SECOND pair of AC PV inputs. Vendor manual: the aPbox "provides
        # the functions of an electrical meter and the ability to remotely
        # disconnect from and connect to PV systems", supports "up to two PV
        # systems" at "2 circuits, max 65 A total", and contains a relay/contactor
        # plus a built-in meter and CTs — which is exactly the two rated inputs and
        # two relays below.
        #
        # The digital I/O lines are grouped here because the cloud's discovery doc
        # pairs them with remote-solar detection, but the aPbox manual describes
        # only TB1 (grid/load), TB2 (solar inverter) and TB3 (aGate comms) — no dry
        # contacts. They are most likely the GATEWAY's own I/O, so they are labelled
        # as unattributed rather than claimed for the aPbox.
        "remote_solar": {
            "enabled": bool(c.get("remoteSolarEn")),
            "mode": c.get("remoteSolarMode"),
            "proximal_installed": bool(c.get("installProximalsolar")),
            "rated_kw": _kw(c.get("solarRatedPower")),
            "input_count": c.get("loadSolarAmount"),
            "inputs": [
                {"input": 1, "rated_kw": _kw(c.get("loadSolar1RatedPower")),
                 "relay": _relay(r.get("loadRelay1Stat", c.get("loadRelay1Stat")))},
                {"input": 2, "rated_kw": _kw(c.get("loadSolar2RatedPower")),
                 "relay": _relay(r.get("loadRelay2Stat", c.get("loadRelay2Stat")))},
            ],
            "mains_rated_kw": _kw(c.get("mainsSolarRatedPower")),
            # 4 lines each, from 1301. Owner unattributed — see note above.
            "digital_in": f.get("diStatus"),
            "digital_out": f.get("doStatus"),
        },
        # Everything else 1707 reports, for context — these are not solar-only.
        "system_relays": {
            "main_1": _relay(r.get("mainRelay1Status")),
            "main_2": _relay(r.get("mainRelay2Status")),
            "grid_2": _relay(r.get("gridRelay2")),
            "black_start": _relay(r.get("blackStartRelay")),
            "smart_circuits": [_relay(r.get(f"smartRelay{n}Status")) for n in (1, 2, 3)],
            "main_sw": {"grid": main_sw[0] if len(main_sw) > 0 else None,
                        "generator": main_sw[1] if len(main_sw) > 1 else None,
                        "solar": main_sw[2] if len(main_sw) > 2 else None},
        },
        "export": {
            # -1 is the firmware's "unlimited", same convention as the grid limits.
            "feed_max_w": None if c.get("grid_feed_max") in (-1, None) else c.get("grid_feed_max"),
            "unlimited": c.get("grid_feed_max") == -1,
        },
        "protection": {
            "protect_time_s": c.get("protectTime"),
            "reconnect_soc_pct": c.get("reSolarSoc"),
        },
        "undecoded": {
            # Held constant while power changed across two samples — not live output.
            "solarPowerGen": c.get("solarPowerGen"),
        },
    }
