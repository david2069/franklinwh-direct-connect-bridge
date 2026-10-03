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


#: aPower model specs (usable/rated kWh + continuous kW), from datasheets — the local API
#: cannot read the aPower model/SKU, so the user picks it; capacity = usable_kwh × count.
#: See FEAT-DEVICE-CAPABILITIES. Values are per UNIT. Owner-provided where noted.
APOWER_SPECS: dict[str, dict[str, Any]] = {
    "aPower X":  {"usable_kwh": 13.6, "rated_kwh": 15.0, "charge_kw": 5.0,  "discharge_kw": 5.0,  "has_mppt": False},
    "aPower 2":  {"usable_kwh": 16.0, "rated_kwh": 16.0, "charge_kw": 10.0, "discharge_kw": 10.0, "has_mppt": False},
    "aPower S":  {"usable_kwh": 15.0, "rated_kwh": 15.0, "charge_kw": 8.0,  "discharge_kw": 10.0, "has_mppt": True},
}


def apower_specs() -> list[dict[str, Any]]:
    """The aPower model spec table as a list (for the Settings picker)."""
    return [{"model": k, **v} for k, v in APOWER_SPECS.items()]
