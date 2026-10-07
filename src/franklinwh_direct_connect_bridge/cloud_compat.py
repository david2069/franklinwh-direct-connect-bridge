"""Cloud-aligned translation layer.

Pure functions (no I/O) that turn the local aGate's cmdType payloads into the
exact JSON shapes the ``franklinwh-cloud`` client returns, so FWHAI can call the
bridge first and fall back to the Cloud API with the same response contract.

The shapes here are hand-replicated from ``franklinwh_cloud.models`` — the models
library is a TEST-ONLY dependency (see ``tests/test_cloud_compat.py``), never a
runtime one. The test asserts key-parity against the real dataclasses, so any
drift in the cloud models is caught there rather than silently diverging.

Vendor typos are intentional and preserved: ``agate_ambient_temparture`` (Current
field) and ``AtuoEn`` (smart-circuit raw key) are misspelled in the real API.
"""

from __future__ import annotations

from typing import Any

from franklinwh_local import catalog

# ── Mode name → Cloud API workMode int ───────────────────────────────────────
# Cloud workMode numbering: TOU=1, Self-Consumption=2, Emergency Backup=3.
# Keyed on a normalised (lowercased) local mode name. The local 1301 payload's
# ``name`` is the canonical mode label (e.g. "Time-of-Use") on this firmware; a
# few spelling variants are included so a differently-cased name still resolves.
_MODE_NAME_TO_WORKMODE = {
    "time-of-use": 1,
    "time of use": 1,
    "tou": 1,
    "self-consumption": 2,
    "self consumption": 2,
    "self": 2,
    "emergency backup": 3,
    "backup": 3,
    "emergency": 3,
}

# run_status value that the FranklinWH app surfaces as "VPP mode".
_VPP_RUN_STATUS = 9

# GridConnectionState.CONNECTED serialises to this string (the enum is a
# ``str, Enum`` so json emits the member value).
_GRID_CONNECTED = "Connected"


def _work_mode_from_name(name: str) -> int:
    """Cloud workMode int for a local mode ``name`` (0 if unrecognised)."""
    return _MODE_NAME_TO_WORKMODE.get((name or "").strip().lower(), 0)


def _empty_current() -> dict[str, Any]:
    """Every ``Current`` field defaulted to its ``empty_stats()`` value.

    Field order and defaults mirror ``franklinwh_cloud.models.Current`` /
    ``empty_stats()``. ``run_status_dec`` is deliberately absent — it is a
    ``@property`` on the dataclass, not a field, so it is NOT in ``asdict``.
    """
    return {
        # ── Power flow (kW) ──
        "solar_production": 0.0,
        "generator_production": 0.0,
        "battery_use": 0.0,
        "grid_use": 0.0,
        "home_load": 0.0,
        "battery_soc": 0.0,
        "switch_1_load": 0.0,
        "switch_2_load": 0.0,
        "v2l_use": 0.0,
        # ── Grid state ──
        "grid_connection_state": _GRID_CONNECTED,
        # ── Operating mode ──
        "work_mode": 0,
        "work_mode_desc": "",
        "device_status": 0,
        "tou_mode": 0,
        "tou_mode_desc": "",
        "run_status": 0,
        "run_status_desc": "",
        # ── Battery pack telemetry ──
        "apower_serial_numbers": "",
        "apower_soc": "",
        "apower_power": "",
        "apower_bms_mode": "",
        # ── Environment ──  [sic: temparture]
        "agate_ambient_temparture": 0.0,
        # ── Primary relays ──
        "grid_relay1": 0,
        "generator_relay": 0,
        "solar_relay1": 0,
        # ── Connectivity ──
        "mobile_signal": 0.0,
        "wifi_signal": 0.0,
        "network_connection": 0,
        # ── V2L / generator ──
        "v2l_enabled": 0,
        "v2l_status": 0,
        "generator_enabled": 0,
        "generator_status": 0,
        # ── Power flow breakdown (kW) ──
        "grid_charging_battery": 0.0,
        "solar_export_to_grid": 0.0,
        "solar_charging_battery": 0.0,
        "battery_export_to_grid": 0.0,
        # ── APbox / remote solar ──
        "apbox_remote_solar": 0.0,
        "remote_solar_enabled": 0,
        "mppt_status": 0,
        "mppt_all_power": 0.0,
        "mppt_active_power": 0.0,
        "mpan_pv1_power": 0.0,
        "mpan_pv2_power": 0.0,
        "remote_solar_pv1": 0.0,
        "remote_solar_pv2": 0.0,
        # ── Alarms ──
        "alarms_count": 0,
        # ── Extended relays (cmdType 211) ──
        "grid_relay2": 0,
        "black_start_relay": 0,
        "pv_relay2": 0,
        "bfpv_apbox_relay": 0,
        # ── Electrical measurements (cmdType 211) ──
        "grid_voltage1": 0.0,
        "grid_voltage2": 0.0,
        "grid_current1": 0.0,
        "grid_current2": 0.0,
        "grid_frequency": 0.0,
        "grid_set_frequency": 0.0,
        "grid_line_voltage": 0.0,
        "generator_voltage": 0.0,
        "load_current1": 0.0,
        "load_current2": 0.0,
        "dsp_run_status": 0,
        "ibg_run_status": 0,
        "electricity_type": 0,
        # ── Active TOU window ──
        "active_tou_name": "",
        "active_tou_dispatch": "",
        "active_tou_dispatch_id": None,
        "active_tou_wave_type": None,
        "active_tou_wave_type_desc": "",
        "active_tou_start": "",
        "active_tou_end": "",
        "active_tou_remaining": "",
        # ── Smart circuit switch states ──
        "switch_1_state": 0,
        "switch_2_state": 0,
        "switch_3_state": 0,
        # ── Effective/display mode ──
        "effective_mode": "",
        # ── APBox / MPPT config flags ──
        "mppt_en_flag": False,
        "mppt_export_en": 0,
        "install_pv1_port": 0,
        "install_pv2_port": 0,
        "remote_solar_mode": 0,
        # ── Hardware install config ──
        "pv_split_ct_en": 0,
        "grid_split_ct_en": 0,
        "install_proximal_solar": 0,
        "is_three_phase_install": 0,
        # ── Load & EV relays (cmdType 211) ──
        "load_relay1": 0,
        "load_relay2": 0,
        "v2l_relay": 0,
        "load_solar_relay1": 0,
        "load_solar_relay2": 0,
    }


def _empty_totals() -> dict[str, Any]:
    """Every ``Totals`` field defaulted to its ``empty_stats()`` value (0.0)."""
    return {
        # ── Battery (kWh) ──
        "battery_charge": 0.0,
        "battery_discharge": 0.0,
        # ── Grid (kWh) ──
        "grid_import": 0.0,
        "grid_export": 0.0,
        # ── Generation (kWh) ──
        "solar": 0.0,
        "generator": 0.0,
        "home_use": 0.0,
        # ── Smart switch energy (kWh) ──
        "switch_1_use": 0.0,
        "switch_2_use": 0.0,
        "v2l_export": 0.0,
        "v2l_import": 0.0,
        # ── Load breakdown by source ──
        "solar_load_kwh": 0.0,
        "grid_load_kwh": 0.0,
        "battery_load_kwh": 0.0,
        "generator_load_kwh": 0.0,
        # ── APbox / MPAN PV (kWh) ──
        "mpan_pv1_wh": 0.0,
        "mpan_pv2_wh": 0.0,
    }


def smart_circuit_detail(payload: dict, cid: int) -> dict[str, Any]:
    """Replicate ``SmartCircuitDetail.from_api_payload(payload, cid)`` exactly.

    Reads the firmware's ``Sw{cid}*`` keys (note the vendor typo ``AtuoEn``) and
    returns the same field set ``dataclasses.asdict()`` would produce for the
    cloud dataclass. Missing keys fall back the same way the cloud does.
    """
    return {
        "id": cid,
        "name": payload.get(f"Sw{cid}Name", ""),
        "mode": payload.get(f"Sw{cid}Mode", 0),
        "is_on": payload.get(f"Sw{cid}Mode", 0) == 1,
        "soc_cutoff_enabled": payload.get(f"Sw{cid}AtuoEn", 0) == 1,  # [sic] AtuoEn
        "soc_cutoff_limit": payload.get(f"Sw{cid}SocLowSet", 0),
        "pro_load_type": payload.get(f"Sw{cid}ProLoad", 0),
        # V1 (legacy) scheduling
        "open_time": payload.get(f"Sw{cid}OpenTime"),
        "close_time": payload.get(f"Sw{cid}CloseTime"),
        "open_time_2": payload.get(f"Sw{cid}OpenTime2"),
        "close_time_2": payload.get(f"Sw{cid}CloseTime2"),
        "load_limit": payload.get(f"Sw{cid}LoadLimit"),
        # V2 (modern) scheduling
        "time_enabled": payload.get(f"Sw{cid}TimeEn"),
        "time_schedules": payload.get(f"Sw{cid}Time"),
        "time_set": payload.get(f"Sw{cid}TimeSet"),
    }


def smart_circuits_map(payload: dict) -> dict[str, Any]:
    """``{"1": {...}, "2": {...}, "3": {...}}`` — mirrors ``get_smart_circuits``.

    Cloud returns ``{int: SmartCircuitDetail}``; over JSON the dict keys become
    strings, so this uses ``str(i)`` for parity with the serialised shape.
    """
    return {str(i): smart_circuit_detail(payload, i) for i in range(1, 4)}


# ── reserves: local mode_list (+ mode_soc) → cloud get_all_mode_soc() ─────────
# Cloud ``get_all_mode_soc`` returns ``list[dict]`` — one entry per operating mode,
# keyed exactly ``workMode / name / soc / minSoc / maxSoc / editSocFlag / active``.
# We build it from the local ``mode_list`` (1726) entries and read min/max SoC from
# the local ``mode_soc`` (1406) per-workMode fields. Emergency Backup (workMode 3)
# has no min/max in 1406, so it falls back to the cloud defaults (0 / 100). The
# local read cannot supply ``editSocFlag`` — it defaults to 0 (the cloud default).

_RESERVE_KEYS = ("workMode", "name", "soc", "minSoc", "maxSoc", "editSocFlag", "active")


def reserves_from_mode_list(mode_list: dict, mode_soc: dict | None = None) -> list[dict[str, Any]]:
    """Cloud ``get_all_mode_soc`` shape from a local ``mode_list`` (+ optional ``mode_soc``).

    Parameters
    ----------
    mode_list : dict
        Raw local ``mode_list`` (1726) payload: ``current_id`` + ``list`` of
        ``{id, name, reserved_soc, scheduling_type, electricity_type}``.
    mode_soc : dict, optional
        Raw local ``mode_soc`` (1406) payload — ``selfMinSoc/selfMaxSoc`` (workMode 2)
        and ``touMinSoc/touMaxSoc`` (workMode 1). When absent, min/max default 0/100.
    """
    ml = mode_list or {}
    soc = mode_soc or {}
    current_id = ml.get("current_id")
    # Per-workMode (min, max) SoC source in the local mode_soc payload. workMode 3
    # (Emergency Backup) is absent → the cloud defaults (0/100) apply below.
    minmax_by_workmode = {
        1: (soc.get("touMinSoc"), soc.get("touMaxSoc")),
        2: (soc.get("selfMinSoc"), soc.get("selfMaxSoc")),
    }
    out: list[dict[str, Any]] = []
    for entry in ml.get("list", []) or []:
        wm = entry.get("scheduling_type")
        lo, hi = minmax_by_workmode.get(wm, (None, None))
        out.append({
            "workMode": wm,                                 # ← scheduling_type
            # Canonical label, NOT the raw local name. The local broker labels the
            # TOU mode with the site's TARIFF (e.g. "Solar & Battery Plan"), which
            # confuses users and developers alike — and the cloud's own
            # getGatewayTouListV2 returns "Time-of-Use" here, so canonicalising
            # IMPROVES parity rather than breaking it.
            "name": catalog.mode_label(entry),
            "soc": entry.get("reserved_soc", 0),
            "minSoc": lo if lo is not None else 0,          # cloud default 0
            "maxSoc": hi if hi is not None else 100,        # cloud default 100
            "editSocFlag": 0,                               # local can't supply
            "active": entry.get("id") == current_id,
        })
    return out


# ── tou: local mode_list (+ tou_schedule) → cloud get_gateway_tou_list() ──────
# The cloud method returns the full API response ``{code, message, result:{...}}``.
# Its ``result`` carries ``currendId`` + ``list`` (the OPERATING-MODE list — the same
# list ``get_all_mode_soc`` parses, each item ``{id, name, workMode, soc, oldIndex,
# editSocFlag}``) plus schedule flags + timers. Locally that mode list is ``mode_list``
# (1726), NOT ``tou_schedule`` (1407, which is only the workday/weekend strategy).
#
# We source ``mode_list`` as the primary read (→ currendId + list), then best-effort
# ENRICH ``result`` with the local ``tou_schedule`` (1408) strategy/flag fields, and
# default the remaining cloud ``result`` keys the method documents.

# Documented cloud result-level keys the local reads can't supply → cloud defaults.
_TOU_RESULT_DEFAULTS = {
    "timers": [],
    "stopMode": 0,
    "stromEn": 0,
    "gridChargeEn": 0,
    "touSendStatus": 0,
}


def tou_from_mode_list(mode_list: dict, tou_schedule: dict | None = None) -> dict[str, Any]:
    """Cloud ``get_gateway_tou_list`` full envelope from a local ``mode_list`` (1726),
    optionally enriched with ``tou_schedule`` (1408) strategy/flag fields.

    Parameters
    ----------
    mode_list : dict
        Raw local ``mode_list`` (1726): ``current_id`` + ``list`` of
        ``{id, name, reserved_soc, scheduling_type, electricity_type}``.
    tou_schedule : dict, optional
        Raw local ``tou_schedule`` (1408): ``touStrategy`` + workday/weekend flags.
        Merged into ``result`` (best-effort); envelope keys (opt/result) are skipped.
    """
    ml = mode_list or {}
    current_id = ml.get("current_id")
    items: list[dict[str, Any]] = []
    for entry in ml.get("list", []) or []:
        items.append({
            "id": entry.get("id"),
            "name": catalog.mode_label(entry),          # canonical, not the tariff
            "workMode": entry.get("scheduling_type"),   # ← scheduling_type
            "soc": entry.get("reserved_soc", 0),
            # Cloud-only per-item keys the local read lacks → cloud defaults.
            "oldIndex": 0,
            "editSocFlag": 0,
            "minSoc": 0,
            "maxSoc": 100,
        })
    result: dict[str, Any] = {"currendId": current_id, "list": items, **_TOU_RESULT_DEFAULTS}
    # Best-effort enrich with the local tou_schedule strategy/flags (drop the wrapper).
    for k, v in (tou_schedule or {}).items():
        if k not in ("opt", "result"):
            result[k] = v
    return {"code": 200, "message": "SUCCESS", "result": result}


# ── mode: local power_flow + mode_list (+ mode_soc, tou_schedule) → cloud get_mode() ──
# Cloud get_mode returns a flat dict for the ACTIVE (or a requested) operating mode,
# aggregating composite (203) + TOU list. Locally: mode_list (1726) supplies the mode
# entry (id/name/workMode/soc), mode_soc (1406) supplies min/max, power_flow (1302)
# supplies run_status. Cloud-portal fields (unread/alarms/valid/deviceStatus) are
# defaulted — the local API has no clean equivalent. Reserve SoC values are read-only
# (cloud-owned). Mode-index rule: workMode == scheduling_type (cloud numbering), never
# the local oldIndex — see the mode-index memory / BACKLOG note.

_MODE_RESULT_DEFAULTS = {
    "deviceStatus": 1, "valid": "1", "unreadMsgCount": 0, "alarmsCount": 0,
    "currentAlarmVOList": None, "report_type": "", "editSocFlag": 0,
}

# cloud workMode → mode_soc (1406) min/max field names
_MODE_SOC_FIELDS = {1: ("touMinSoc", "touMaxSoc"), 2: ("selfMinSoc", "selfMaxSoc")}


def mode_from_reads(power_flow: dict, mode_list: dict, mode_soc: dict | None = None,
                    tou_schedule: dict | None = None,
                    requested_workmode: int | None = None) -> dict[str, Any]:
    """Cloud ``get_mode`` flat dict from local reads. Returns the ACTIVE mode
    (``requested_workmode=None``) or the mode whose cloud ``workMode`` matches. Selects
    the mode entry by ``scheduling_type`` (== cloud workMode) / ``current_id`` — never by
    the local oldIndex numbering."""
    pf = power_flow or {}
    ml = mode_list or {}
    current_id = ml.get("current_id")
    entries = ml.get("list", []) or []
    if requested_workmode is not None:
        target = next((e for e in entries
                       if e.get("scheduling_type") == int(requested_workmode)), None)
    else:
        target = next((e for e in entries if e.get("id") == current_id), None)
    if target is None:
        which = requested_workmode if requested_workmode is not None else current_id
        return {"error": f"mode {which} not found in mode_list"}

    work_mode = target.get("scheduling_type")
    name = catalog.mode_label(target)          # canonical, never the site tariff
    tariff = target.get("name", "")
    min_soc, max_soc = 0, 100
    if mode_soc and work_mode in _MODE_SOC_FIELDS:
        mn, mx = _MODE_SOC_FIELDS[work_mode]
        min_soc = mode_soc.get(mn, 0)
        max_soc = mode_soc.get(mx, 100)
    run_status = int(pf.get("run_status", 0) or 0)
    result: dict[str, Any] = {
        "currendId": target.get("id"),
        "workMode": work_mode,
        "modeName": name,
        "name": name,
        # The raw local label, kept so the tariff is not lost by canonicalising.
        "tariffName": tariff if tariff and tariff != name else None,
        "soc": target.get("reserved_soc", 0),
        "minSoc": min_soc,
        "maxSoc": max_soc,
        "run_status": run_status,
        "run_desc": catalog.run_status_desc(run_status),
        "electricityType": target.get("electricity_type", 1),
        "offgridState": 1 if run_status in (5, 6, 7) else 0,   # off-grid run_status codes
        **_MODE_RESULT_DEFAULTS,
    }
    if work_mode == 1:                                          # TOU mode_specific
        ts = {k: v for k, v in (tou_schedule or {}).items()
              if k not in ("opt", "result", "reason")}
        if ts:
            result["touScheduleList"] = ts
        result["touAlertMessage"] = ""
        result["touSendStatus"] = ""
    elif work_mode == 3:                                        # Emergency Backup mode_specific
        result["backupForeverFlag"] = ""
        result["oldIndex"] = 0
        result["nextWorkMode"] = ""
        result["durationMinute"] = "0"
    return result


# ── runtime: local ibg_run_status (1708) → cloud get_runtime_data() ───────────
# Cloud ``get_runtime_data`` returns the raw ``result`` dict (relay states + temps).
# The local 1708 read supplies only ``ibgRunStatus / name / energyMode``; the extra
# relay & temperature fields the cloud response carries (documented on the method:
# gridRelay2, pvRelay2, BlackStartRelay, sinLTemp, sinHTemp, t_amb) are defaulted.

_RUNTIME_EXTRA_DEFAULTS = {
    "gridRelay2": 0, "pvRelay2": 0, "BlackStartRelay": 0,
    "sinLTemp": 0, "sinHTemp": 0, "t_amb": 0,
}


def runtime_from_ibg_run_status(payload: dict) -> dict[str, Any]:
    """Cloud ``get_runtime_data`` shape from a local ``ibg_run_status`` (1708) payload."""
    src = payload or {}
    return {
        "ibgRunStatus": src.get("ibgRunStatus", 0),
        "name": src.get("name", ""),
        "energyMode": src.get("energyMode", 0),
        **_RUNTIME_EXTRA_DEFAULTS,
    }


# ── power-info: local relay_status (1710) → cloud get_power_info() (raw 211) ──
# Cloud ``get_power_info`` returns the raw cmdType-211 payload: electrical
# measurements (voltages/currents/frequencies), extended relays, run-status. The
# local ``relay_status`` (1710) read supplies only the primary contactor
# adhesion/open flags, so the electrical + extended-relay fields are defaulted and
# the four local relay flags are passed through unchanged.

# Raw 211 keys the cloud reads out of get_power_info() (see stats.py get_stats).
_POWER_INFO_DEFAULTS = {
    # Electrical measurements
    "gridLineVol": 0, "gridVol1": 0, "gridVol2": 0,
    "gridCurr1": 0, "gridCurr2": 0, "gridFreq": 0, "dspSetFreq": 0,
    "genVoltage": 0, "loadCurr1": 0, "loadCurr2": 0,
    # Extended relays
    "gridRelay2": 0, "blackStartRelay": 0, "pvRelay2": 0, "BFPVApboxRelay": 0,
    "loadRelay1Stat": 0, "loadRelay2Stat": 0, "evRelayStat": 0,
    "loadSolarRelay1Stat": 0, "loadSolarRelay2Stat": 0,
    # Run status
    "dspRunStatus": 0, "ibgRunStatus": 0, "electricity_type": 0,
}

# Local relay_status (1710) contactor fields — passed through unchanged.
_RELAY_STATUS_FIELDS = ("gridRelayAdhesion", "gridRelayOpen",
                        "genRelayAdhesion", "genRelayOpen")


def power_info_from_relay_status(relay_status: dict) -> dict[str, Any]:
    """Cloud ``get_power_info`` (raw 211) shape from a local ``relay_status`` (1710)."""
    out = dict(_POWER_INFO_DEFAULTS)
    src = relay_status or {}
    for k in _RELAY_STATUS_FIELDS:
        if k in src:
            out[k] = src[k]
    return out


# ── device-info: local device_info (1116) → cloud get_device_info() ───────────
# Cloud ``get_device_info`` returns the raw Device-Info-V2 API response (a passthrough
# with no fixed schema). The local ``device_info`` (1116) is a different but analogous
# installer/user config payload (usrName, distributor, installerId, ...). We pass it
# through unchanged — the two schemas differ, so this is a best-effort equivalent.

def device_info_passthrough(device_info: dict) -> dict[str, Any]:
    """Return the local ``device_info`` (1116) payload unchanged (cloud passthrough)."""
    return dict(device_info or {})


# ── network: local network_interfaces (1118) → cloud get_network_info() ───────
# Reproduces the structured cloud ``get_network_info`` output (currentNetType, wifi,
# eth0, eth1, operator, awsStatus). The firmware field names (wifiMAC/wifiDHCP/…) are
# shared with the cloud cmdType-317 ``commSetPara`` block, so we resolve them the same
# way the cloud does — accepting either a nested ``commSetPara`` or flat top-level keys.

def network_from_interfaces(network_interfaces: dict) -> dict[str, Any]:
    """Cloud ``get_network_info`` shape from a local ``network_interfaces`` (1118)."""
    parsed = network_interfaces or {}
    # Same commSetPara extraction the cloud uses (result nested, result int, or flat).
    result = parsed.get("result") if isinstance(parsed, dict) else parsed
    if isinstance(result, dict):
        comm = result.get("commSetPara", result)
    elif isinstance(parsed, dict):
        comm = parsed.get("commSetPara", parsed)
    else:
        comm = {}
    if not isinstance(comm, dict):
        comm = parsed if isinstance(parsed, dict) else {}
    return {
        "currentNetType": comm.get("currentNetType"),
        "wifi": {
            "mac": comm.get("wifiMAC"),
            "dhcp": bool(comm.get("wifiDHCP", 0)),
            "ip": comm.get("wifiStaticIP"),
            "dns": comm.get("wifiDNS"),
            "gateway": comm.get("wifiGateWay"),
        },
        "eth0": {
            "mac": comm.get("eth0MAC"),
            "dhcp": bool(comm.get("eth0DHCP", 0)),
            "ip": comm.get("eth0StaticIP"),
            "dns": comm.get("eth0DNS"),
            "gateway": comm.get("eth0GateWay"),
        },
        "eth1": {
            "mac": comm.get("eth1MAC"),
            "dhcp": bool(comm.get("eth1DHCP", 0)),
            "ip": comm.get("eth1StaticIP"),
            "dns": comm.get("eth1DNS"),
            "gateway": comm.get("eth1GateWay"),
        },
        "operator": {
            "mac": comm.get("operatorMAC"),
            "dns": comm.get("operatorDNS"),
            "rssi": comm.get("operatorRSSI"),
        },
        "awsStatus": comm.get("awsStatus"),
    }


def stats_from_power_flow(pf: dict, *, sw_payload: dict | None = None) -> dict[str, Any]:
    """Build the full cloud ``Stats`` shape from a local ``power_flow`` (1301) payload.

    Returns ``{"current": {...}, "totals": {...}, "is_stale": False}`` where every
    ``Current``/``Totals`` key is present (defaulted to its ``empty_stats()`` value)
    and the core fields are overwritten from the local payload.

    Parameters
    ----------
    pf : dict
        Raw local ``power_flow`` payload (cmdType 1301). Expected keys: ``p_sun``,
        ``p_gen``, ``p_fhp``, ``p_uti``, ``p_load``, ``soc``, ``t_amb``,
        ``run_status``, ``mode``, ``name``. Daily-kWh keys are mapped when present.
    sw_payload : dict, optional
        Raw ``smart_circuits`` payload (cmdType 1409). When given, the three
        ``switch_{n}_state`` fields are set from ``Sw{n}Mode``.
    """
    pf = pf or {}
    current = _empty_current()
    totals = _empty_totals()

    name = pf.get("name", "") or ""
    run_status = int(pf.get("run_status", 0) or 0)
    work_mode = _work_mode_from_name(name)

    # effective_mode: what the system is DOING. VPP (run_status 9) wins; otherwise
    # the operating-mode label. Uses the local catalog's RUN_STATUS labels for parity
    # with the cloud vocabulary.
    if run_status == _VPP_RUN_STATUS:
        effective_mode = catalog.run_status_desc(_VPP_RUN_STATUS)
    else:
        effective_mode = name

    # ── Core power flow (local 1301 → cloud Current) ──
    current["solar_production"] = pf.get("p_sun", 0.0)
    current["generator_production"] = pf.get("p_gen", 0.0)
    current["battery_use"] = pf.get("p_fhp", 0.0)
    current["grid_use"] = pf.get("p_uti", 0.0)
    current["home_load"] = pf.get("p_load", 0.0)
    current["battery_soc"] = pf.get("soc", 0.0)
    current["agate_ambient_temparture"] = pf.get("t_amb", 0.0)  # [sic]

    # ── Mode / run status ──
    current["run_status"] = run_status
    current["run_status_desc"] = catalog.run_status_desc(run_status)
    current["work_mode"] = work_mode
    current["work_mode_desc"] = name
    current["tou_mode"] = pf.get("mode", 0) or 0
    current["tou_mode_desc"] = name
    current["effective_mode"] = effective_mode
    current["grid_connection_state"] = _GRID_CONNECTED

    # ── Smart-circuit switch states (optional 1409 payload) ──
    if sw_payload:
        current["switch_1_state"] = sw_payload.get("Sw1Mode", 0) or 0
        current["switch_2_state"] = sw_payload.get("Sw2Mode", 0) or 0
        current["switch_3_state"] = sw_payload.get("Sw3Mode", 0) or 0

    # ── Daily-kWh totals ──
    # The local 1301 payload MAY carry daily-kWh fields under the same raw names the
    # cloud uses (runtimeData.kwh_*). They are mapped defensively when present; the
    # synthetic emulator does not emit them, so they stay at the empty default there.
    current_totals_map = {
        "battery_charge": "kwh_fhp_chg",
        "battery_discharge": "kwh_fhp_di",
        "grid_import": "kwh_uti_in",
        "grid_export": "kwh_uti_out",
        "solar": "kwh_sun",
        "generator": "kwh_gen",
        "home_use": "kwh_load",
    }
    for out_key, raw_key in current_totals_map.items():
        if raw_key in pf:
            totals[out_key] = pf.get(raw_key, 0.0)

    return {"current": current, "totals": totals, "is_stale": False}
