"""Ported field-schema metadata — reverse index keyed by RAW API key.

This is a DATA-ONLY port of ``franklinwh_cloud/cli_commands/schema.py`` (the
``franklinwh-cli schema`` tables). franklinwh-cloud is NOT a runtime dependency of the
bridge, so we copy the dicts here rather than import them. Keeping the field/group/unit
metadata in one place lets the Device tab and the dashboard Live Points panel label +
group raw device fields identically (the FWHAI ``schema --live`` look).

The public surface is:

* ``FIELD_SCHEMA`` — ``{ raw_key: {"label", "group", "unit"[, "enum"]} }`` reverse index.
  BOTH the collapsed base key (``pro_load_pwr``) AND the per-index keys (``pro_load_pwr[0]``,
  ``main_sw[0]`` → grid_relay1, …) are present, so an array field can be broken out into one
  labelled row per element instead of rendering ``[1,0,1]`` on a single row.
* ``describe_field(raw_key)`` — one lookup, index-tolerant, ``None`` when unknown.
* ``describe_indexed(base_key, i)`` — the schema entry for ``base_key[i]`` if defined, else a
  generic ``{label: "<base label> [i]", group, unit}`` derived from the base key.
* ``ENUMS`` — ``{ raw_key: {code: description} }`` decode tables (e.g. ``run_status``),
  also attached onto the matching ``FIELD_SCHEMA`` entry as ``"enum"``.

NB: the ``unit`` here is the CLOUD presentation unit. The LOCAL ``power_flow`` (1301)
payload uses different scales (watts vs kW) — value FORMATTING is chosen per field type in
the UI (``$store.app.fmtField``), not from this unit string. Label + group come from here.
"""

from __future__ import annotations

import re

# ── Source tables (verbatim data from franklinwh_cloud schema.py) ──────────────
# Format: field_attr -> (raw_api_key, source, units, group). Only the raw_api_key,
# units and group are consumed here; ``source`` is retained for provenance/parity.

_CURRENT_SCHEMA = {
    "solar_production":         ("p_sun",              "203/runtimeData",  "kW",    "Power Flow"),
    "generator_production":     ("p_gen",              "203/runtimeData",  "kW",    "Power Flow"),
    "battery_use":              ("p_fhp",              "203/runtimeData",  "kW",    "Power Flow"),
    "grid_use":                 ("p_uti",              "203/runtimeData",  "kW",    "Power Flow"),
    "home_load":                ("p_load",             "203/runtimeData",  "kW",    "Power Flow"),
    "battery_soc":              ("soc",                "203/runtimeData",  "%",     "Power Flow"),
    "switch_1_load":            ("pro_load_pwr[0]",    "311/sw_data",      "kW",    "Power Flow"),
    "switch_2_load":            ("pro_load_pwr[1]",    "311/sw_data",      "kW",    "Power Flow"),
    "v2l_use":                  ("CarSWPower",         "311/sw_data",      "kW",    "Power Flow"),
    "grid_connection_state":    ("derived",            "derived",          "enum",  "Grid State"),
    "work_mode":                ("currentWorkMode",    "203/result",       "int",   "Mode"),
    "work_mode_desc":           ("derived",            "derived",          "str",   "Mode"),
    "device_status":            ("deviceStatus",       "203/result",       "int",   "Mode"),
    "tou_mode":                 ("mode",               "203/runtimeData",  "int",   "Mode"),
    "tou_mode_desc":            ("name",               "203/runtimeData",  "str",   "Mode"),
    "run_status":               ("run_status",         "203/runtimeData",  "int",   "Mode"),
    "run_status_desc":          ("RUN_STATUS[run_status]", "derived",      "str",   "Mode"),
    "effective_mode":           ("derived",            "derived",          "str",   "Mode"),
    "apower_serial_numbers":    ("fhpSn",              "203/runtimeData",  "list",  "Battery Packs"),
    "apower_soc":               ("fhpSoc",             "203/runtimeData",  "list",  "Battery Packs"),
    "apower_power":             ("fhpPower",           "203/runtimeData",  "list",  "Battery Packs"),
    "apower_bms_mode":          ("bms_work",           "203/runtimeData",  "list",  "Battery Packs"),
    "agate_ambient_temparture": ("t_amb",              "203/runtimeData",  "°C",    "Environment"),
    "grid_relay1":              ("main_sw[0]",         "203/runtimeData",  "relay", "Relays"),
    "generator_relay":          ("main_sw[1]",         "203/runtimeData",  "relay", "Relays"),
    "solar_relay1":             ("main_sw[2]",         "203/runtimeData",  "relay", "Relays"),
    "mobile_signal":            ("signal",             "203/runtimeData",  "%",     "Connectivity"),
    "wifi_signal":              ("wifiSignal",         "203/runtimeData",  "%",     "Connectivity"),
    "network_connection":       ("connType",           "203/runtimeData",  "int",   "Connectivity"),
    "v2l_enabled":              ("v2lModeEnable",      "203/runtimeData",  "bool",  "V2L"),
    "v2l_status":               ("v2lRunState",        "203/runtimeData",  "int",   "V2L"),
    "generator_enabled":        ("genEn",              "203/runtimeData",  "bool",  "Generator"),
    "generator_status":         ("genStat",            "203/runtimeData",  "int",   "Generator"),
    "grid_charging_battery":    ("gridChBat",          "203/runtimeData",  "kW",    "Power Flow"),
    "solar_export_to_grid":     ("soOutGrid",          "203/runtimeData",  "kW",    "Power Flow"),
    "solar_charging_battery":   ("soChBat",            "203/runtimeData",  "kW",    "Power Flow"),
    "battery_export_to_grid":   ("batOutGrid",         "203/runtimeData",  "kW",    "Power Flow"),
    "apbox_remote_solar":       ("apbox20Pv",          "203/runtimeData",  "kW",    "APbox/MPPT"),
    "remote_solar_enabled":     ("remoteSolarEn",      "203/runtimeData",  "bool",  "APbox/MPPT"),
    "remote_solar_mode":        ("remoteSolarMode",    "solarHaveVo",      "int",   "APbox/MPPT"),
    "mppt_status":              ("mpptSta",            "203/runtimeData",  "int",   "APbox/MPPT"),
    "mppt_all_power":           ("mpptAllPower",       "203/runtimeData",  "kW",    "APbox/MPPT"),
    "mppt_active_power":        ("mpptActPower",       "203/runtimeData",  "kW",    "APbox/MPPT"),
    "mpan_pv1_power":           ("mPanPv1Power",       "203/runtimeData",  "kW",    "APbox/MPPT"),
    "mpan_pv2_power":           ("mPanPv2Power",       "203/runtimeData",  "kW",    "APbox/MPPT"),
    "remote_solar_pv1":         ("remoteSolar1Power",  "203/runtimeData",  "kW",    "APbox/MPPT"),
    "remote_solar_pv2":         ("remoteSolar2Power",  "203/runtimeData",  "kW",    "APbox/MPPT"),
    "mppt_en_flag":             ("mpptEnFlag",         "203/runtimeData",  "bool",  "APbox/MPPT Flags"),
    "mppt_export_en":           ("mpptExportEn",       "203/runtimeData",  "bool",  "APbox/MPPT Flags"),
    "install_pv1_port":         ("installPv1Port",     "203/runtimeData",  "0/1",   "APbox/MPPT Flags"),
    "install_pv2_port":         ("installPv2Port",     "203/runtimeData",  "0/1",   "APbox/MPPT Flags"),
    "pv_split_ct_en":           ("pvSplitCtEn",        "203/runtimeData",  "0/1",   "Hardware Config"),
    "grid_split_ct_en":         ("gridSplitCtEn",      "203/runtimeData",  "0/1",   "Hardware Config"),
    "install_proximal_solar":   ("installProximalsolar", "203/runtimeData", "0/1",  "Hardware Config"),
    "is_three_phase_install":   ("isThreePhaseInstall", "203/runtimeData",  "0/1",  "Hardware Config"),
    "alarms_count":             ("currentAlarmVOList", "203/result",       "count", "Alarms"),
    "grid_relay2":              ("gridRelayStat",      "211/result",       "relay", "Extended Relays (211)"),
    "black_start_relay":        ("bFpVApboxRelay",     "211/result",       "relay", "Extended Relays (211)"),
    "pv_relay2":                ("pvRelay2",           "211/result",       "relay", "Extended Relays (211)"),
    "bfpv_apbox_relay":         ("BFPVApboxRelay",     "211/result",       "relay", "Extended Relays (211)"),
    "load_relay1":              ("loadRelay1Stat",     "211/result",       "relay", "Load & V2L Relays (211)"),
    "load_relay2":              ("loadRelay2Stat",     "211/result",       "relay", "Load & V2L Relays (211)"),
    "v2l_relay":                ("evRelayStat",        "211/result",       "relay", "Load & V2L Relays (211)"),
    "load_solar_relay1":        ("loadSolarRelay1Stat", "211/result",      "relay", "Load & V2L Relays (211)"),
    "load_solar_relay2":        ("loadSolarRelay2Stat", "211/result",      "relay", "Load & V2L Relays (211)"),
    "grid_voltage1":            ("gridVol1",           "211/result",       "V",     "Power Measurements (211)"),
    "grid_voltage2":            ("gridVol2",           "211/result",       "V",     "Power Measurements (211)"),
    "grid_current1":            ("gridCurr1",          "211/result",       "A",     "Power Measurements (211)"),
    "grid_current2":            ("gridCurr2",          "211/result",       "A",     "Power Measurements (211)"),
    "load_current1":            ("loadCurr1",          "211/result",       "A",     "Power Measurements (211)"),
    "load_current2":            ("loadCurr2",          "211/result",       "A",     "Power Measurements (211)"),
    "grid_frequency":           ("gridFreq",           "211/result",       "Hz",    "Power Measurements (211)"),
    "grid_set_frequency":       ("dspSetFreq",         "211/result",       "Hz",    "Power Measurements (211)"),
    "grid_line_voltage":        ("gridLineVol",        "211/result",       "V",     "Power Measurements (211)"),
    "generator_voltage":        ("genVoltage",         "211/result",       "V",     "Power Measurements (211)"),
    "dsp_run_status":           ("dspRunStatus",       "211/result",       "int",   "Power Measurements (211)"),
    "ibg_run_status":           ("ibgRunStatus",       "211/result",       "int",   "Power Measurements (211)"),
    "electricity_type":         ("electricity_type",   "211/result",       "int",   "Power Measurements (211)"),
    "switch_1_state":           ("pro_load[0]",        "311/runtimeData",  "0/1",   "Smart Circuits"),
    "switch_2_state":           ("pro_load[1]",        "311/runtimeData",  "0/1",   "Smart Circuits"),
    "switch_3_state":           ("pro_load[2]",        "311/runtimeData",  "0/1",   "Smart Circuits"),
}

_TOTALS_SCHEMA = {
    "battery_charge":       ("kwh_fhp_chg",   "203/runtimeData",  "kWh",  "Battery"),
    "battery_discharge":    ("kwh_fhp_di",    "203/runtimeData",  "kWh",  "Battery"),
    "grid_import":          ("kwh_uti_in",    "203/runtimeData",  "kWh",  "Grid"),
    "grid_export":          ("kwh_uti_out",   "203/runtimeData",  "kWh",  "Grid"),
    "solar":                ("kwh_sun",       "203/runtimeData",  "kWh",  "Generation"),
    "generator":            ("kwh_gen",       "203/runtimeData",  "kWh",  "Generation"),
    "home_use":             ("kwh_load",      "203/runtimeData",  "kWh",  "Generation"),
    "switch_1_use":         ("SW1ExpEnergy",  "311/sw_data",      "kWh",  "Smart Circuits"),
    "switch_2_use":         ("SW2ExpEnergy",  "311/sw_data",      "kWh",  "Smart Circuits"),
    "v2l_export":           ("CarSWExpEnergy", "311/sw_data",     "kWh",  "V2L"),
    "v2l_import":           ("CarSWImpEnergy", "311/sw_data",     "kWh",  "V2L"),
    "solar_load_kwh":       ("kwhSolarLoad",  "203/runtimeData",  "kWh",  "Load Breakdown"),
    "grid_load_kwh":        ("kwhGridLoad",   "203/runtimeData",  "kWh",  "Load Breakdown"),
    "battery_load_kwh":     ("kwhFhpLoad",    "203/runtimeData",  "kWh",  "Load Breakdown"),
    "generator_load_kwh":   ("kwhGenLoad",    "203/runtimeData",  "kWh",  "Load Breakdown"),
    "mpan_pv1_wh":          ("mpanPv1Wh",     "203/runtimeData",  "Wh",   "APbox/MPPT"),
    "mpan_pv2_wh":          ("mpanPv2Wh",     "203/runtimeData",  "Wh",   "APbox/MPPT"),
}

_GRID_LIMITS_SCHEMA = {
    "globalGridChargeMax":      ("globalGridChargeMax",    "get_power_control_settings", "kW / -1", "Global Limits"),
    "globalGridDischargeMax":   ("globalGridDischargeMax", "get_power_control_settings", "kW / -1", "Global Limits"),
    "globalSettingStatus":      ("globalSettingStatus",    "get_power_control_settings", "int",     "Global Limits"),
    "gridFeedMax":              ("gridFeedMax",            "get_power_control_settings", "kW / -1", "Feed-In (Export)"),
    "gridFeedMaxFlag":          ("gridFeedMaxFlag",        "get_power_control_settings", "int",     "Feed-In (Export)"),
    "gridMax":                  ("gridMax",                "get_power_control_settings", "kW / -1", "Import"),
    "gridMaxFlag":              ("gridMaxFlag",            "get_power_control_settings", "int",     "Import"),
    "gridFlag":                 ("gridFlag",               "get_power_control_settings", "bool",    "Grid Connection"),
    "solarFlag":                ("solarFlag",              "get_power_control_settings", "bool",    "Grid Connection"),
    "notControlExportSolar":    ("notControlExportSolar",  "get_power_control_settings", "bool",    "Feed-In (Export)"),
    "peakDemandGridMax":        ("peakDemandGridMax",      "get_power_control_settings", "kW / -1", "Peak Demand"),
    "bbDischargePower":         ("bbDischargePower",       "get_power_control_settings", "kW",      "Backup Battery"),
    "sgipFlag":                 ("sgipFlag",               "get_power_control_settings", "0/1",     "Programmes"),
    "itcFlag":                  ("itcFlag",                "get_power_control_settings", "0/1",     "Programmes"),
    "isNem3":                   ("isNem3",                 "get_power_control_settings", "0/1",     "Programmes"),
    "isCalifornia":             ("isCalifornia",           "get_power_control_settings", "0/1",     "Programmes"),
}

_TOU_SCHEMA = {
    "startHourTime":        ("startHourTime",  "setTouSchedule",   "HH:MM", "Time Block"),
    "endHourTime":          ("endHourTime",    "setTouSchedule",   "HH:MM", "Time Block"),
    "name":                 ("name",           "getTouList",       "str",   "Configuration"),
    "dispatchId":           ("dispatchId",     "setTouSchedule",   "int",   "Configuration"),
    "waveType":             ("waveType",       "setTouSchedule",   "int",   "Tariff/Pricing"),
    "targetSoc":            ("targetSoc",      "setTouSchedule",   "int",   "Configuration"),
}

_MODE_SCHEMA = {
    "soc":                  ("soc",                "getTouList",   "float", "SOC Limits"),
    "maxSoc":               ("maxSoc",             "getTouList",   "float", "SOC Limits"),
    "minSoc":               ("minSoc",             "getTouList",   "float", "SOC Limits"),
    "dischargeDepthSoc":    ("dischargeDepthSoc",  "getTouList",   "float", "SOC Limits"),
    "complianceSoc":        ("complianceSoc",      "getTouList",   "float", "SOC Limits"),
}

_ALL_TABLES = (
    _CURRENT_SCHEMA, _TOTALS_SCHEMA, _GRID_LIMITS_SCHEMA, _TOU_SCHEMA, _MODE_SCHEMA,
)

# ── Label prettification ───────────────────────────────────────────────────────
# Whole-attribute overrides where a mechanical title-case would read wrong
# (misspellings in the source, or a domain term that isn't the literal words).
_LABEL_FIXUPS = {
    "agate_ambient_temparture": "Ambient temperature",
    "apower_soc":               "Pack SoC",
    "apower_power":             "Pack power",
    "apower_serial_numbers":    "Pack serial numbers",
    "apower_bms_mode":          "Pack BMS mode",
    "tou_mode":                 "Operating Mode",
    "tou_mode_desc":            "Operating Mode name",
}

# Word-level fixups (acronyms / mixed-case domain terms) applied to every token.
_WORD_FIXUPS = {
    "soc": "SoC", "tou": "TOU", "pv": "PV", "pv1": "PV1", "pv2": "PV2",
    "v2l": "V2L", "ev": "EV", "kwh": "kWh", "wh": "Wh", "mppt": "MPPT",
    "apbox": "APbox", "ibg": "IBG", "dsp": "DSP", "bms": "BMS", "der": "DER",
    "pf": "PF", "id": "ID", "ct": "CT", "ac": "AC", "dc": "DC", "sn": "SN",
    "hz": "Hz", "mpan": "MPAN", "sgip": "SGIP", "itc": "ITC", "nem3": "NEM3",
    "bb": "BB",
}


def _prettify(attr: str) -> str:
    """Human label for a python attribute name (``battery_use`` -> "Battery use")."""
    if attr in _LABEL_FIXUPS:
        return _LABEL_FIXUPS[attr]
    words = attr.split("_")
    out = []
    for i, w in enumerate(words):
        if w in _WORD_FIXUPS:
            out.append(_WORD_FIXUPS[w])
        elif i == 0:
            out.append(w[:1].upper() + w[1:])
        else:
            out.append(w)
    return " ".join(out)


def _base_key(raw_key: str) -> str:
    """Strip a trailing array index so ``pro_load_pwr[0]`` -> ``pro_load_pwr``."""
    return re.sub(r"\[[^\]]*\]$", "", str(raw_key))


# ── Local-only supplement ──────────────────────────────────────────────────────
# Keys the CLOUD schema tables don't cover but that appear in the LOCAL reads the
# UI surfaces (power_flow 1301, solar_pv 1903, relay_status 1709). Merged INTO
# FIELD_SCHEMA (overriding the cloud entry when a key is redefined here) so these
# fields are labelled + grouped instead of dumped in "Other". Format matches the
# reverse index: raw_key -> {label, group, unit}.
_LOCAL_SUPPLEMENT: dict[str, dict[str, str]] = {
    # -- power_flow (1301): TOU tariff-tier energy buckets (arrays, kWh) ----------
    "sharp":  {"label": "Sharp-period energy",  "group": "TOU", "unit": "kWh"},
    "peak":   {"label": "Peak-period energy",   "group": "TOU", "unit": "kWh"},
    "flat":   {"label": "Flat-period energy",   "group": "TOU", "unit": "kWh"},
    "valley": {"label": "Valley-period energy", "group": "TOU", "unit": "kWh"},
    # -- power_flow (1301): other locals that were falling to "Other" -------------
    "slaver_stat":   {"label": "Slave status",     "group": "Status",     "unit": "int"},
    "elecnet_state": {"label": "Grid-net state",   "group": "Status",     "unit": "int"},
    "infi_status":   {"label": "Inverter status",  "group": "Status",     "unit": "int"},
    "genStat":       {"label": "Generator status", "group": "Generator",  "unit": "int"},
    "cd_alm":        {"label": "Alarm code",       "group": "Alarms",     "unit": "int"},
    "offgridreason": {"label": "Off-grid reason",  "group": "Grid State", "unit": "int"},
    # doStatus/diStatus (1301): 4-element digital-output / digital-input arrays (the LOCAL
    # names for the cloud runtime's do/di). Broken out per line into a "Digital I/O" group.
    "doStatus":      {"label": "Digital outputs",   "group": "Digital I/O", "unit": "0/1"},
    "diStatus":      {"label": "Digital inputs",    "group": "Digital I/O", "unit": "0/1"},
    "doStatus[0]":   {"label": "Digital output 1",  "group": "Digital I/O", "unit": "0/1"},
    "doStatus[1]":   {"label": "Digital output 2",  "group": "Digital I/O", "unit": "0/1"},
    "doStatus[2]":   {"label": "Digital output 3",  "group": "Digital I/O", "unit": "0/1"},
    "doStatus[3]":   {"label": "Digital output 4",  "group": "Digital I/O", "unit": "0/1"},
    "diStatus[0]":   {"label": "Digital input 1",   "group": "Digital I/O", "unit": "0/1"},
    "diStatus[1]":   {"label": "Digital input 2",   "group": "Digital I/O", "unit": "0/1"},
    "diStatus[2]":   {"label": "Digital input 3",   "group": "Digital I/O", "unit": "0/1"},
    "diStatus[3]":   {"label": "Digital input 4",   "group": "Digital I/O", "unit": "0/1"},
    # -- solar_pv (1903) ---------------------------------------------------------
    # Firmware / serial tags from the 1101 login manifest and 1833. These are
    # otherwise unreadable four-letter codes; the Health card already spelled some
    # of them out, so the detail view should not be the worse of the two.
    "protocolVer":  {"label": "Protocol version",        "group": "Firmware"},
    "IBG_VER":      {"label": "Gateway firmware",        "group": "Firmware"},
    "APP_VER":      {"label": "Local service",           "group": "Firmware"},
    "AWS_VER":      {"label": "Cloud (IoT) service",     "group": "Firmware"},
    "SL_VER":       {"label": "SL_VER (undecoded)",      "group": "Firmware"},
    "METER_VER":    {"label": "Meter firmware",          "group": "Firmware"},
    "FPGA_VER":     {"label": "FPGA",                    "group": "Firmware"},
    "DCDC_VER":     {"label": "DC-DC converter",         "group": "Firmware"},
    "INV_VER":      {"label": "Inverter",                "group": "Firmware"},
    "BMS_VER":      {"label": "BMS",                     "group": "Firmware"},
    "BL_VER":       {"label": "Bootloader",              "group": "Firmware"},
    "TH_VER":       {"label": "Thermal board",           "group": "Firmware"},
    "SyHdVersion":  {"label": "Hardware model id",       "group": "Firmware"},
    "IBG_SN":       {"label": "Gateway serial",          "group": "Serials"},
    "FHP_SN":       {"label": "aPower serial",           "group": "Serials"},
    "BMS_SN":       {"label": "BMS serial",              "group": "Serials"},
    "PE_SN":        {"label": "Power-electronics serial", "group": "Serials"},
    "fhp_sn":       {"label": "aPower serial",           "group": "Serials"},
    "ibg_sn":       {"label": "Gateway serial",          "group": "Serials"},
    "bms_sn":       {"label": "BMS serial",              "group": "Serials"},
    "pe_sn":        {"label": "Power-electronics serial", "group": "Serials"},
    "ibg_ver":      {"label": "Gateway firmware",        "group": "Firmware"},
    "ibg_iot":      {"label": "Cloud (IoT) service",     "group": "Firmware"},
    "ibg_local":    {"label": "Local service",           "group": "Firmware"},
    "bms_ver":      {"label": "BMS",                     "group": "Firmware"},
    "pe_ver":       {"label": "Power electronics",       "group": "Firmware"},
    "installPV1port": {"label": "PV1 port installed", "group": "Solar PV", "unit": "0/1"},
    "installPV2port": {"label": "PV2 port installed", "group": "Solar PV", "unit": "0/1"},
    "PV1RatedPower":  {"label": "PV1 rated power",    "group": "Solar PV", "unit": "kW"},
    "PV2RatedPower":  {"label": "PV2 rated power",    "group": "Solar PV", "unit": "kW"},
    "solarRelayStat": {"label": "Solar relay",        "group": "Relays",   "unit": "relay"},
    "loadRelay1Stat": {"label": "Load relay 1",       "group": "Relays",   "unit": "relay"},
    "loadRelay2Stat": {"label": "Load relay 2",       "group": "Relays",   "unit": "relay"},
    "solarPower":     {"label": "Solar power",        "group": "Solar PV", "unit": "kW"},
    "solarPowerGen":  {"label": "Solar power (gen)",  "group": "Solar PV", "unit": "kW"},
    "reSolarSoc":     {"label": "Reconnect solar SoC", "group": "Solar PV", "unit": "%"},
    # -- relay_status (1709) -----------------------------------------------------
    "gridRelayAdhesion": {"label": "Grid relay adhesion", "group": "Relays", "unit": "relay"},
    "gridRelayOpen":     {"label": "Grid relay open",     "group": "Relays", "unit": "relay"},
    "genRelayAdhesion":  {"label": "Gen relay adhesion",  "group": "Relays", "unit": "relay"},
    "genRelayOpen":      {"label": "Gen relay open",      "group": "Relays", "unit": "relay"},
}


# ── Enum decode tables ─────────────────────────────────────────────────────────
# ``{raw_key: {code: description}}``. Sourced from ``franklinwh_local.catalog`` so the
# local broker and the bridge agree byte-for-byte. Import-guarded: fieldschema must
# stay importable even if franklinwh_local isn't installed (unit-test / packaging safety).
def _load_enums() -> dict[str, dict[int, str]]:
    try:
        from franklinwh_local import catalog as _cat
        return {"run_status": dict(_cat.RUN_STATUS)}
    except Exception:  # pragma: no cover - fallback keeps import safe
        return {"run_status": {
            0: "Standby", 1: "Charging", 2: "Discharging", 3: "Reserved 3",
            4: "Reserved 4", 5: "Off-Grid Standby", 6: "Off-Grid Charging",
            7: "Off-Grid Discharging", 8: "Debug Mode", 9: "VPP mode",
        }}


ENUMS: dict[str, dict[int, str]] = _load_enums()


# ── Build the reverse index: raw_key -> {label, group, unit[, enum]} ───────────
def _build() -> dict[str, dict]:
    index: dict[str, dict] = {}
    for table in _ALL_TABLES:
        for attr, (raw_key, _source, units, group) in table.items():
            if raw_key == "derived":            # not a real device key
                continue
            entry = {"label": _prettify(attr), "group": group, "unit": units}
            base = _base_key(raw_key)
            index.setdefault(base, entry)
            # KEEP the per-index key too (main_sw[0] -> "Grid relay1"), so array
            # fields break out into one labelled row per element in the UI.
            if raw_key != base:
                index.setdefault(raw_key, entry)
    # Local-only supplement OVERRIDES the cloud entry where redefined (e.g. the
    # solar_pv load relays are grouped under "Relays" for the Live Points render).
    for key, entry in _LOCAL_SUPPLEMENT.items():
        index[key] = dict(entry)
    # Attach enum decode tables onto their field entry (exposed via /api/schema).
    for key, mapping in ENUMS.items():
        index.setdefault(key, {"label": _prettify(key), "group": "Other", "unit": "int"})
        index[key] = {**index[key], "enum": mapping}
    return index


FIELD_SCHEMA: dict[str, dict] = _build()


def describe_field(raw_key: str) -> dict | None:
    """Metadata for a raw device key, or ``None`` if unknown.

    An exact match (incl. an indexed key like ``main_sw[0]``) is preferred; failing
    that the array index is stripped and the base key is looked up (``pro_load_pwr[0]``
    matches ``pro_load_pwr``). Returns a ``{"label", "group", "unit"[, "enum"]}`` dict.
    """
    if raw_key is None:
        return None
    return FIELD_SCHEMA.get(str(raw_key)) or FIELD_SCHEMA.get(_base_key(raw_key))


def describe_indexed(base_key: str, i: int) -> dict:
    """Schema entry for ``base_key[i]`` — the specific per-index entry when defined
    (``main_sw[0]`` → grid_relay1), else a generic ``{label: "<base label> [i]", …}``
    derived from the base key. Never ``None`` (always renderable)."""
    indexed = f"{base_key}[{i}]"
    hit = FIELD_SCHEMA.get(indexed)
    if hit is not None:
        return hit
    base = FIELD_SCHEMA.get(_base_key(base_key)) or {}
    return {
        "label": f'{base.get("label", base_key)} [{i}]',
        "group": base.get("group", "Other"),
        "unit":  base.get("unit", ""),
    }
