"""Gateway hardware registry keyed on ``SyHdVersion`` — pure data, no I/O.

``SyHdVersion`` arrives in the 1101 login manifest, so **every** aGate session
already carries it at no extra cost. It is FWHAI's ``sysHdVersionInt``, and it
identifies the gateway model — which means the region question that smart-circuit
detection was answering by inference has an authoritative answer after all.

Provenance: ``SyHdVersion`` → SKU comes from FWHAI's FranklinWH Device DB (Admin →
Gateways / Accessories, v0.6.0). SKU → vendor model name and accessory compatibility
come from **FranklinWH's "Backwards Compatibility Statement", revision US V1.0
(21 July 2026)** — a US/Canada document that contains **no AU models at all**, so it
cannot settle anything about the AU gateway.

Note the naming mismatch: FWHAI displays "aGate X-10 / X-20"; the vendor document calls
the same SKUs "aGate X 1.1 / 1.3". ``model`` keeps FWHAI's label (so the two UIs agree)
and ``vendor_model`` carries FranklinWH's. Accessory identifiers 200–302 are **FWHAI-internal**,
not FranklinWH values — the vendor API returns only ``accessoryType`` (3 = generator,
4 = smart circuits), and flag-detected accessories have no type at all. They are kept
here purely so the two projects can be cross-referenced.

``circuits`` is the *model's* channel count, from
``franklinwh-cloud/docs/CAPABILITY_RESOLUTION_SPEC.md`` Rule 2 plus the AU hardware in
hand — FWHAI's own table leaves the column empty. It is a strong prior, **not** proof
for a given site: a gateway that supports three circuits may have no enclosure fitted
at all. Detection still runs; this narrows it.
"""

from __future__ import annotations

from typing import Any

#: ``amps`` is the MODEL's rated service capacity, not the site's main breaker.
#: Worth stating because the two have been confused before: FWHAI reports 100 A for
#: this AU model while the site's own install profile reads 63 — different facts.
GATEWAYS: dict[int, dict[str, Any]] = {
    100: {"model": "aGate X-10",    "sku": "AGT-R1V1-US", "country": "US",
          "amps": 200, "circuits": 3, "vendor_model": "aGate X 1.1"},
    101: {"model": "aGate X-20",    "sku": "AGT-R1V2-US", "country": "US",
          "amps": 200, "circuits": 3, "vendor_model": "aGate X 1.3"},
    # Not in the vendor document (US/CAN only) — vendor_model unknown, not guessed.
    102: {"model": "aGate X-01-AU", "sku": "AGT-R1V1-AU", "country": "AU",
          "amps": 100, "circuits": 2, "vendor_model": None},
    103: {"model": "aGate X 20 (US)", "sku": "AGT-R1V3-US", "country": "US",
          "amps": 200, "circuits": 3, "vendor_model": "aGate X 1.3/1.3.1"},
    104: {"model": "aGate X 20 (US)", "sku": "AGT-R1V3-US", "country": "US",
          "amps": 200, "circuits": 3, "vendor_model": "aGate X 1.3/1.3.1"},
}

#: Accessories, keyed by FWHAI-internal id. ``api_type`` is the vendor's
#: ``accessoryType``; ``None`` means FWHAI detects it from a feature flag instead.
ACCESSORIES: dict[int, dict[str, Any]] = {
    201: {"name": "Generator Module", "sku": "ACCY-GENV1-US", "kind": "generator",
          "api_type": 3, "gateways": [100, 101], "vendor_fit": "aGate X 1.0/1.1"},
    203: {"name": "Generator Module", "sku": "ACCY-GENV2-US", "kind": "generator",
          "api_type": 3, "gateways": [103, 104], "vendor_fit": "aGate X 1.3/1.3.1"},
    301: {"name": "Generator Module", "sku": "ACCY-GENV1-AU", "kind": "generator",
          "api_type": 3, "gateways": [102]},
    202: {"name": "Smart Circuits", "sku": "ACCY-SCV1-US", "kind": "smart_circuits",
          "api_type": 4, "gateways": [100, 101], "vendor_fit": "aGate X 1.0/1.1",
          "note": "pre-assembled smart circuit; does not support aPower S"},
    # DISCREPANCY: FWHAI lists this as compatible with 102 (AU), but the vendor
    # document scopes SCV2 to "aGate X 1.3/1.3.1". Recorded, not silently corrected —
    # the vendor document covers no AU hardware, so neither source settles it.
    204: {"name": "Smart Circuits", "sku": "ACCY-SCV2-US", "kind": "smart_circuits",
          "api_type": 4, "gateways": [102, 103, 104], "vendor_fit": "aGate X 1.3/1.3.1",
          "note": "FWHAI lists AU gateway 102; vendor doc scopes SCV2 to 1.3/1.3.1"},
    # DISCOVER_IMPLEMENTATION_PLAN.md:102 ("AU SC (302) has no V2L port") refers to
    # this row — 302 is the FWHAI id, not a FranklinWH one.
    302: {"name": "Smart Circuits", "sku": "ACCY-SCV1-AU", "kind": "smart_circuits",
          "api_type": 4, "gateways": [102], "v2l": False},
    251: {"name": "aPbox", "sku": "ACCY-RCV1-US", "kind": "apbox",
          "api_type": None, "gateways": "all"},
    252: {"name": "Split-CT", "sku": "ACCY-CT200V1-US", "kind": "split_ct",
          "api_type": None, "gateways": "all", "vendor_fit": "aGate X 1.0/1.1"},
    253: {"name": "aHub", "sku": "ACCY-AHUBV1-US", "kind": "ahub",
          "api_type": None, "gateways": "all"},
    254: {"name": "Meter Adapter Controller", "sku": "MAC-R1V1-US", "kind": "mac1",
          "api_type": None, "gateways": "all"},
}

#: Accessories in the vendor document that FWHAI's table does not carry. Listed for
#: completeness of the parts catalogue; none are software-visible.
VENDOR_ONLY_ACCESSORIES: tuple[dict[str, Any], ...] = (
    {"name": "Split CT Kit", "sku": "ACCY-CT200V2-US", "vendor_fit": "aGate X 1.3/1.3.1"},
    {"name": "Backup Expansion Lug Kit", "sku": "ACCY-BLV2-US",
     "vendor_fit": "aGate X 1.3/1.3.1"},
    {"name": "Main Load Relay", "sku": "ACCY-MRV2-US", "vendor_fit": "aGate X 1.3/1.3.1"},
    {"name": "Inner Panel", "sku": "ACCY-IPV1-US", "vendor_fit": "aGate X 1.3/1.3.1"},
    {"name": "Floor Mounting Bracket", "sku": "ACCY-FMBV2-US",
     "vendor_fit": "aPower 2, aPower S"},
)

#: Fleet limits from the vendor document — relevant to multi-aPower sites.
FLEET_LIMITS: dict[str, dict[str, Any]] = {
    "aGate X 1.0/1.1": {"max_apowers": 15,
                        "note": "max 8 when mixing aPower X with aPower 2"},
    "aGate X 1.3/1.3.1": {"max_apowers": 15, "max_apower_s": 8},
    "MAC 1": {"max_apowers": 4},
}


def gateway(sy_hd_version: Any) -> dict[str, Any] | None:
    """Look up a gateway model. Unknown ids return ``None`` — never a guess."""
    try:
        return GATEWAYS.get(int(sy_hd_version))
    except (TypeError, ValueError):
        return None


def compatible(sy_hd_version: Any, kind: str | None = None) -> list[dict[str, Any]]:
    """Accessories this gateway model can take, optionally filtered by kind."""
    try:
        gid = int(sy_hd_version)
    except (TypeError, ValueError):
        return []
    out = []
    for aid, a in ACCESSORIES.items():
        gws = a["gateways"]
        if gws != "all" and gid not in gws:
            continue
        if kind and a["kind"] != kind:
            continue
        out.append({"id": aid, **a})
    return sorted(out, key=lambda a: a["id"])


def describe(manifest: dict | None) -> dict[str, Any]:
    """Identify the gateway from a 1101 login manifest."""
    m = manifest or {}
    ver = m.get("SyHdVersion")
    info = gateway(ver)
    return {
        "sy_hd_version": ver,
        "known": info is not None,
        "model": (info or {}).get("model"),
        "vendor_model": (info or {}).get("vendor_model"),
        "sku": (info or {}).get("sku"),
        "country": (info or {}).get("country"),
        "rated_amps": (info or {}).get("amps"),
        "expected_circuits": (info or {}).get("circuits"),
        "compatible_accessories": compatible(ver),
        "firmware": {k: m[k] for k in ("IBG_VER", "APP_VER", "AWS_VER", "protocolVer")
                     if k in m},
        "serial": m.get("IBG_SN"),
    }


#: aPower model specs (usable/rated kWh + continuous kW). The local API cannot read the
#: aPower model or SKU, so the user picks it; capacity = usable_kwh × count. Per UNIT.
#:
#: PROVENANCE, since these numbers now size a dispatch:
#:
#: * The model→power MAPPING is verified in ``franklinwh-cloud``'s
#:   ``const/device_catalog.json`` + ``discovery.compile_capabilities``, where the SKU
#:   encodes the rating: ``APR-05K…`` = aPower X, ``APR-10K…`` = aPower 2,
#:   ``APRS-10K/11K…`` = aPower S (stackable, MPPT). Checked 2026-10-16.
#: * The owner's statement (FEAT-DEVICE-CAPABILITIES): "5 kW fixed per aPower, except
#:   aPower S which is 10 kW variable."
#: * **aPower S 8 kW charge / 10 kW discharge: CONFIRMED by the vendor datasheet.**
#:   *FranklinWH aPower S datasheet, document version V1.9* (SKUs APRS-10K15V1-US,
#:   APRS-10K15V1.1-US, APRS-10K15V1.1DCP-US; nameplate "aPower S-10"), retrieved
#:   2026-10-16 from https://www.franklinwh.com/document/apower-s-datasheet — owner-supplied
#:   link. Verbatim: "Max Real Power (Charge) 8 kW continuous"; "Max Real Power (Discharge)
#:   – With PV Input 11.5 kW continuous / – Battery Only 10 kW continuous".
#:
#:   So the asymmetry is real and this table was right, though for a reason nobody had
#:   written down. ``discharge_kw`` holds the **battery-only** 10 kW, which is the correct
#:   number for sizing a battery dispatch: the 11.5 kW figure includes PV flowing through
#:   the hybrid inverter, which is not what a force command controls. The extra headroom is
#:   recorded as ``discharge_with_pv_kw`` rather than being dropped.
#: * **aPower 2: CONFIRMED by the vendor datasheet**, and this table had been WRONG on
#:   three counts. *"aPower V2.0 Datasheet-EN"* (PDF title; created 2026-10-09; SKUs
#:   APR-10K15V2-US, APR-10K15V2U-US, APR-10K15V2DCP-US; nameplate "aPower X-20"),
#:   retrieved 2026-10-16 from https://www.franklinwh.com/document/apower-2-datasheet —
#:   owner-supplied link. Verbatim: "Usable System Energy 15 kWh AC per unit, up to 15
#:   units per aGate"; "Max Real Power (charge) 8 kW continuous"; "Max Real Power
#:   (Discharge) 10 kW / 11.5 kVA continuous".
#:
#:   Corrected here: charge 10 → **8 kW**, usable 16 → **15 kWh**, rated 16 → **15 kWh**.
#:   The 10 kW in the SKU (``APR-10K…``) is the DISCHARGE rating; reading it as both
#:   directions overstated charging by 25%, and the 16 kWh had no source at all.
#:   So BOTH confirmed models charge at 8 kW and discharge at 10 kW — the SKU names the
#:   discharge figure, which is the trap this table fell into twice.
#: * **AU hardware: a different unit, not a relabel.** *FranklinWH System datasheet,
#:   document version V1.7, dated 2026-09-10* (retrieved 2026-10-16 from
#:   https://www.franklinwh.com/document/system-datasheet — owner-supplied link), which
#:   covers **aPower X-02-AU** (SKU APR-05K15V1-AU) and **aGate X-01-AU** (SKU AGT-R1V1-AU)
#:   and states it is the Australia/New Zealand product.
#:
#:   Verbatim for aPower X-02-AU: "Usable Energy 15 kWh"; "Rated Battery Capacity 16 kWh";
#:   "Rated Input / Output Power 5 kW (per aPower with a system maximum of 20kW)"; "Peak
#:   Power 10 kW for 10 sec (per aPower with a system maximum of 40kW)"; 230/240 VAC,
#:   50 Hz; "Round Trip Efficiency 89%"; "Warranty 12 years".
#:
#:   The US "aPower X" row is 13.6 kWh usable / 15 kWh rated with a 15-year warranty —
#:   so the AU unit holds MORE usable energy at the same 5 kW rate. Treating them as one
#:   model would understate an AU site's capacity by 1.4 kWh per aPower, which matters
#:   because battery capacity here is usable_kwh × count.
APOWER_SPECS: dict[str, dict[str, Any]] = {
    "aPower X":  {"usable_kwh": 13.6, "rated_kwh": 15.0, "charge_kw": 5.0,  "discharge_kw": 5.0,
                  "country": "US", "skus": ["APR-05K1V1-US", "APR-05K11V1-US",
                                            "APR-05K15V1-US"],
                  "has_mppt": False},
    # The AU variant is a DIFFERENT unit, not a relabel: 15 kWh usable (16 kWh rated),
    # 230/240 V 50 Hz, 12-year warranty. Same 5 kW rate. Datasheet V1.7 — see above.
    # The AU SKUs carry a -AU suffix and a different middle group (05K13 / 05K15).
    "aPower X-02-AU": {"usable_kwh": 15.0, "rated_kwh": 16.0, "charge_kw": 5.0, "discharge_kw": 5.0,
                       "country": "AU", "peak_kw": 10.0,
                       "skus": ["APR-05K15V1-AU", "APR-05K13V1-AU", "APR-05K13V2-AU"],
                       "has_mppt": False},
    # Datasheet "aPower V2.0" (nameplate aPower X-20): 15 kWh AC, charge 8 kW,
    # discharge 10 kW / 11.5 kVA. Our table previously said 16 kWh and 10 kW charge —
    # both wrong, see the provenance note above.
    "aPower 2":  {"usable_kwh": 15.0, "rated_kwh": 15.0, "charge_kw": 8.0, "discharge_kw": 10.0,
                  "apparent_kva": 11.5, "country": "US",
                  "skus": ["APR-10K15V2-US", "APR-10K15V2U-US", "APR-10K15V2DCP-US"],
                  "has_mppt": False},
    # Datasheet V1.9: charge 8 kW, discharge 10 kW battery-only / 11.5 kW with PV input.
    "aPower S":  {"usable_kwh": 15.0, "rated_kwh": 15.0, "charge_kw": 8.0,  "discharge_kw": 10.0,
                  "discharge_with_pv_kw": 11.5, "country": "US",
                  "skus": ["APRS-10K15V1-US", "APRS-10K15V1.1-US", "APRS-10K15V1.1DCP-US",
                           "APRS-11K15V2-US"],
                  "has_mppt": True},
}


def apower_by_sku(sku: str | None) -> tuple[str, dict[str, Any]] | None:
    """``(model, spec)`` for a full or partial aPower SKU, or None.

    Matching on the SKU is what lets this table line up with FWHAI's device DB and the
    cloud catalog, both of which are keyed on SKU and country rather than on a display
    name. Matching is case-insensitive and accepts a prefix, because the suffix carries
    the transmitter/DCP variant and not the electrical rating.
    """
    s = (sku or "").strip().upper()
    if not s:
        return None
    for model, spec in APOWER_SPECS.items():
        for known in spec.get("skus", []):
            k = known.upper()
            if s == k or s.startswith(k) or k.startswith(s):
                return (model, spec)
    return None


def apower_power_w(model: str | None, count: int = 1) -> tuple[int, int] | None:
    """``(charge_w, discharge_w)`` for ``count`` aPowers of ``model``, or None if unknown.

    The datasheet rating is PER UNIT, so a two-aPower site is twice one unit. None rather
    than a default: "we do not know this model" and "this model is 5 kW" are different
    answers, and only one of them should ever size a dispatch.
    """
    spec = APOWER_SPECS.get((model or "").strip())
    if not spec:
        return None
    n = max(1, int(count or 1))
    return (int(spec["charge_kw"] * 1000 * n), int(spec["discharge_kw"] * 1000 * n))


def apower_specs() -> list[dict[str, Any]]:
    """The aPower model spec table as a list (for the Settings picker)."""
    return [{"model": k, **v} for k, v in APOWER_SPECS.items()]
