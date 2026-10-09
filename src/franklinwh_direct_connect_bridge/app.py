"""FastAPI app: health + read endpoints (Phase 0/1). MQTT + full UI come later."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

import datetime as _dt
import json as _json

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from starlette.requests import Request

from franklinwh_local.transport import TransportError

from . import __version__, client, db
from . import environment
from . import ha_instances
from . import scheduler
from . import fieldschema
from . import logbuffer

# ── Legal disclaimer (unofficial app) ─────────────────────────────────────────
#: One-line audit stamp logged once at startup and on first UI connection.
DISCLAIMER_ISSUES_URL = "https://github.com/david2069/franklinwh-direct-connect-bridge/issues"
DISCLAIMER_LINE = (
    "franklinwh-direct-connect-bridge | UNOFFICIAL software - NOT affiliated with or endorsed by "
    "FranklinWH | provided AS-IS, no warranty, use at your own risk | may break without notice "
    "from upstream API/firmware changes | do NOT contact FranklinWH support about this app - "
    f"raise issues at {DISCLAIMER_ISSUES_URL} | MIT License."
)
_disclaimer_logged = False


def _log_disclaimer_once() -> None:
    global _disclaimer_logged
    if not _disclaimer_logged:
        logging.getLogger("franklinwh_direct_connect_bridge").info(DISCLAIMER_LINE)
        _disclaimer_logged = True
from . import bms_record
from . import providers
from . import energy_flow as _eflow
from . import state
from . import workers as _workers
from .config import get_settings, gateway_list, metrics_active, save_override
from .ha_supervisor import apply_supervisor_mqtt, discover_mqtt
from .notify import Notifier
from .poller import run_gateway
from . import supervisor
from . import mockgw
from .publish import entities
from .state import GatewayState, get_state, get_gateway, gateways as get_gateways

#: Bridge process start — for the Network tab's uptime. Module import ≈ process start.
_STARTED_AT = time.time()

# Named ranges → span in seconds (Power History chart windows). Aligned with the FranklinWH
# Modbus Bridge range menu (Live/30m/1h/2h/4h/6h/8h/12h/18h/24h/3d/5d/7d/30d).
RANGE_SECONDS = {
    "live": 900, "30m": 1800, "1h": 3600, "2h": 7200, "4h": 14400, "6h": 21600,
    "8h": 28800, "12h": 43200, "18h": 64800, "24h": 86400, "3d": 259200,
    "5d": 432000, "7d": 604800, "30d": 2592000,
}
# Default aggregation bucket per span so a chart gets ~60–300 points (0 = raw, no bucketing).
_DEFAULT_BUCKETS = {
    "live": 0, "30m": 30, "1h": 60, "2h": 60, "4h": 120, "6h": 300, "8h": 240,
    "12h": 300, "18h": 600, "24h": 600, "3d": 1800, "5d": 3600, "7d": 3600, "30d": 14400,
}


def _resolve_bucket(range_: str, start: int, end: int,
                    bucket: int | None, points: int | None) -> int | None:
    """Pick an aggregation bucket (seconds). Explicit ``bucket`` wins; else derive one
    from ``points`` or a sensible per-span default. Returns None only when raw is fine."""
    if bucket is not None:
        return bucket if bucket > 0 else None
    if points is not None and points > 0:
        return max(1, (end - start) // points)
    return _DEFAULT_BUCKETS.get(range_, _DEFAULT_BUCKETS["6h"])

_TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
log = logging.getLogger("franklinwh_direct_connect_bridge")


def _asset_version() -> str:
    """Cache-bust token that tracks the ACTUAL front-end files, not just __version__ — so a
    rebuild always invalidates the browser cache even when the version string is unchanged.
    Hash of (version + newest static/template mtime). Cheap; recomputed per index() request."""
    root = Path(__file__).parent
    newest = 0.0
    for sub in ("static", "templates"):
        for p in (root / sub).rglob("*"):
            if p.is_file():
                try:
                    newest = max(newest, p.stat().st_mtime)
                except OSError:
                    pass
    import hashlib
    return hashlib.sha1(f"{__version__}:{newest}".encode()).hexdigest()[:10]


def _roster_entry(gw: GatewayState) -> dict:
    """One /api/gateways row, derived from the gateway's poller-maintained cache. Never
    raises — an empty/cold cache yields ok:false with null soc/mode."""
    summ = gw.last_summary or {}
    power = summ.get("power") or {}
    fwb = summ.get("firmware") or {}
    ok = bool(summ.get("ok"))
    rs = power.get("run_status")
    rs = int(rs) if isinstance(rs, (int, float)) else None
    _dk_kind, _dk_prog = _dispatch_kind(gw)
    from . import devicedb as _ddb
    _hw = getattr(gw, "sy_hd_version", None)
    _dm = _ddb.gateway(_hw) if _hw is not None else None
    return {
        "id": gw.id,
        "sy_hd_version": _hw,
        "model_detail": (_dm or {}).get("model"),        # e.g. "aGate X-01-AU"
        "model_country": (_dm or {}).get("country"),
        "label": gw.label or gw.configured_host or gw.id,
        "host": gw.active_host or gw.configured_host,
        "configured_host": gw.configured_host,
        "serial": gw.serial or fwb.get("IBG_SN"),
        "firmware": fwb.get("IBG_VER") or gw.firmware,
        "ok": ok,
        "stale": bool(summ.get("stale")),
        "soc": power.get("soc"),
        "mode": power.get("mode"),
        # Run-status enum (local 1301) — the source of truth for the top-nav pill and the
        # per-gateway off-grid / VPP badges (FEAT-TOPNAV-RUNSTATUS). 5/6/7 = islanded, 9 = VPP.
        "run_status": rs,
        "run_status_desc": _run_status_desc(rs),
        "off_grid": rs in (5, 6, 7),
        # Dispatch badge: "vpp" (cloud-confirmed) | "force" (Modbus M704 WSet) | None.
        "vpp": _dk_kind is not None,
        "vpp_kind": _dk_kind,
        "vpp_programme": _dk_prog,
        "mqtt_connected": gw.mqtt_connected,
        "cached": bool(gw.last_summary),
        "updated": ok and not bool(summ.get("stale")),
    }


def _run_status_desc(rs: int | None) -> str | None:
    """Human label for a run_status enum via the local catalog (cloud-parity vocabulary)."""
    if rs is None:
        return None
    try:
        from franklinwh_local import catalog as _cat
        return _cat.run_status_desc(rs)
    except Exception:  # pragma: no cover — never break a roster row on a lookup
        return None


def _dispatch_kind(gw) -> tuple:
    """Classify the active battery dispatch for the badge: ('vpp', programme) when the CLOUD
    confirms a VPP (and the read is fresh), ('force', None) when only the Modbus M704 WSet
    says a force is active, else (None, None). Cloud wins — the local/Modbus APIs cannot tell
    a genuine VPP from a local force_charge (see FEAT-VPP-CLOUD-RUNSTATUS)."""
    import time as _t
    from . import cloud_status as _cs
    cloud_fresh = (getattr(gw, "cloud_vpp", None) is not None
                   and (_t.time() - (getattr(gw, "cloud_ts", 0) or 0)) < _cs.STALE_AFTER_S)
    if cloud_fresh and gw.cloud_vpp:
        return "vpp", getattr(gw, "cloud_programme", None)
    if getattr(gw, "vpp_active", None):
        return "force", None
    return None, None


class ModeReq(BaseModel):
    mode: str                           # id / full name / alias: tou | self | backup
    confirm: bool = False               # consequential: changes the physical operating mode


class BillingImportReq(BaseModel):
    """A Modbus bridge ``/api/tariff/history`` payload to backfill into our history."""
    periods: list[dict] = Field(default_factory=list)
    gateway: str | None = None          # local gateway to attribute the periods to


class BillingImportModbusReq(BaseModel):
    """Fetch closed periods from a Modbus bridge (login → /api/tariff/history) and import them."""
    source_url: str = ""                # e.g. http://host.docker.internal:8100 (else MODBUS_BRIDGE_URL)
    username: str = "admin"
    password: str = "admin"
    gateway: str | None = None
    dry_run: bool = False               # preview: fetch + count, don't write


class OffgridReq(BaseModel):
    on: bool
    soc: int = 5
    confirm: bool = False               # consequential: disconnects/reconnects the grid

class GridLimitsReq(BaseModel):
    # Grid power-plane limits (1701). kW numbers; -1 = unlimited. None = leave unchanged.
    grid_soft_limit: float | None = None   # import cap  -> gridSoftLimit
    grid_hard_limit: float | None = None   # export cap  -> gridHardLimit
    kw_rate_power: float | None = None     # charge-from-grid -> kwRatePower
    export_enable: bool | None = None      # -> gridExportEnable (can STOP export)
    pcs_discharge: bool | None = None      # -> isPcsDischgEn (can STOP discharge)
    confirm: bool = False                  # consequential + UNVERIFIED write
    dry_run: bool = False                  # preview the exact frame; don't send
    cloud_crosscheck: bool = True          # also read the cloud global caps as a witness


class DisclaimerAckReq(BaseModel):
    client_id: str | None = None


class ModbusToggleReq(BaseModel):
    enabled: bool | None = None
    host_override: str | None = None   # blank = auto-derive from the gateway
    port_override: int | None = None


class RestoreReq(BaseModel):
    confirm: bool = False               # consequential: overwrites the live database


class NotifyTriggersBody(BaseModel):
    master: bool | None = None
    triggers: dict | None = None        # {event: {enabled: bool, threshold?: int}}


class CallReq(BaseModel):
    opt: int = 0                        # 0 = read; non-zero = write (gated by allow_writes)
    data: dict = {}                     # extra dataArea fields merged alongside opt


class DerCommsReq(BaseModel):
    sunspec_modbus: bool | None = None  # toggle SunSpec Modbus (sunsMdEn); None = leave
    ieee2030_5: bool | None = None      # toggle IEEE 2030.5 / SEP2 enable; None = leave


class RebootReq(BaseModel):
    confirm: bool = False               # must be true — reboot is DESTRUCTIVE


class DispatchReq(BaseModel):
    # HYBRID-CAPABILITIES Phase 2 — battery dispatch via the resolved Modbus provider.
    action: str                         # charge | discharge | standby | release
    power_w: int | None = None
    power_pct: int | None = None
    duration_s: int | None = None       # watchdog seconds (0 = no limit)
    target_soc: int | None = None       # charge/discharge to this SoC %, then release


# -- cloud-aligned write request models (mirror franklinwh-cloud contracts) ------
# NOTE: kept at module level — a local (in-function) pydantic model under
# `from __future__ import annotations` re-raises field annotations as strings and
# 422s at request time. See the read-facade models above.
class SetModeReq(BaseModel):
    # Cloud workMode 1=Time-of-Use / 2=Self-Consumption / 3=Emergency Backup, or a
    # name/alias (tou/self/backup/...). Reserve SOC + backup-forever/next-mode/duration
    # are cloud-only and are NOT applied locally (surfaced in not_applied_locally).
    requestedOperatingMode: int | str
    requestedSOC: int | None = None
    reqbackupForeverFlag: int | None = None
    reqnextWorkMode: int | str | None = None
    reqdurationMinutes: int | None = None
    confirm: bool = False               # consequential: changes the physical operating mode


class GridStatusReq(BaseModel):
    status: str                         # cloud GridStatus name/value: NORMAL/DOWN/OFF (0/1/2)
    soc: int = 5                        # floor SoC % to hold while islanded


class SmartCircuitStateReq(BaseModel):
    circuit: int                        # 1, 2 or 3
    turn_on: bool


class CircuitPowerReq(BaseModel):
    on: bool


class ScheduleWindow(BaseModel):
    enabled: bool = True
    start: str                          # "HH:MM"
    end: str                            # "HH:MM"


class CircuitScheduleReq(BaseModel):
    windows: list[ScheduleWindow] = []


class GenWindowReq(BaseModel):
    enabled: bool
    start: str | None = None            # "HH:MM"
    end: str | None = None


class GenExerciseReq(BaseModel):
    enabled: bool | None = None
    every_days: int | None = None
    day: int | None = None
    start: str | None = None
    minutes: int | None = None


class HaInstanceCreate(BaseModel):
    name: str
    base_url: str
    token: str | None = None
    is_default: bool = False
    enabled: bool = True


class HaInstanceUpdate(BaseModel):
    name: str | None = None
    base_url: str | None = None
    token: str | None = None
    is_default: bool | None = None
    enabled: bool | None = None


class GatewayCreate(BaseModel):
    label: str
    host: str = ""
    port: int = 9000
    enabled: bool = True
    is_default: bool = False
    is_mock: bool = False
    mock_seed: int | None = None
    mock_units: int = 1
    publish_ha: bool = True          # mocks default OFF via the UI, honoured in Phase 2
    description: str = ""


class GatewayUpdate(BaseModel):
    label: str | None = None
    host: str | None = None
    port: int | None = None
    enabled: bool | None = None
    is_default: bool | None = None
    mock_units: int | None = None
    publish_ha: bool | None = None
    description: str | None = None
    meter_id: str | None = None      # which meter this gateway connects to


class SiteCreate(BaseModel):
    name: str
    timezone: str = ""
    latitude: float | None = None
    longitude: float | None = None
    postcode: str = ""
    currency: str = ""
    region: str = ""
    is_default: bool = False


class SiteUpdate(BaseModel):
    name: str | None = None
    timezone: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    postcode: str | None = None
    currency: str | None = None
    region: str | None = None
    is_default: bool | None = None


class MeterCreate(BaseModel):
    site_id: str
    name: str = "Meter 1"
    meter_number: str = ""
    ac_type: str = "single"          # single | split | three
    rated_amps: float | None = None
    pto_status: str = "unknown"      # unknown | pending | approved | exempt
    pto_reference: str = ""          # PTO / grid-connection approval reference
    timezone: str = ""
    utility_id: str | None = None
    tariff_id: str | None = None
    is_default: bool = False


class MeterUpdate(BaseModel):
    site_id: str | None = None
    name: str | None = None
    meter_number: str | None = None
    ac_type: str | None = None
    rated_amps: float | None = None
    pto_status: str | None = None
    pto_reference: str | None = None
    timezone: str | None = None
    utility_id: str | None = None
    tariff_id: str | None = None
    is_default: bool | None = None


class UtilityCreate(BaseModel):
    name: str = ""
    network_dnsp: str = ""
    country: str = ""
    plan_type: str = "unknown"
    export_allowed: bool = True
    solar_export_allowed: bool = True
    battery_export_allowed: bool = True
    export_limit_kw: float | None = None
    charging_allowed: bool = True
    discharging_allowed: bool = True
    export_note: str = ""
    effective_start: str | None = None      # provider tenure (retailer switch, AU/NZ)
    effective_end: str | None = None


class UtilityUpdate(BaseModel):
    name: str | None = None
    network_dnsp: str | None = None
    country: str | None = None
    plan_type: str | None = None
    export_allowed: bool | None = None
    solar_export_allowed: bool | None = None
    battery_export_allowed: bool | None = None
    export_limit_kw: float | None = None
    charging_allowed: bool | None = None
    discharging_allowed: bool | None = None
    export_note: str | None = None
    effective_start: str | None = None
    effective_end: str | None = None


class TariffProfileImport(BaseModel):
    type: str | None = None
    version: int | None = None
    profile: dict
    effective_start: str | None = None      # optional retailer-from date for the new utility


class TariffCreate(BaseModel):
    utility_id: str
    name: str = ""
    pricing: dict | None = None
    demand_window: dict | None = None
    bonus_window: dict | None = None
    charge_window: dict | None = None
    fixed_charges: list | None = None
    billing_cycle_day: int = 1
    plan_version: str = ""
    effective_start: str | None = None
    effective_end: str | None = None


class TariffUpdate(BaseModel):
    utility_id: str | None = None
    name: str | None = None
    pricing: dict | None = None
    demand_window: dict | None = None
    bonus_window: dict | None = None
    charge_window: dict | None = None
    fixed_charges: list | None = None
    billing_cycle_day: int | None = None
    plan_version: str | None = None
    effective_start: str | None = None
    effective_end: str | None = None


class MqttGroupsBody(BaseModel):
    groups: list[str] = []


class SystemSetupBody(BaseModel):
    """Per-gateway System Setup overrides. Each optional; null reverts to the derived value."""
    solar_type: str | None = None
    solar_kwp: float | None = None
    generator_input: bool | None = None
    grid_forming: bool | None = None
    whole_home_backup: bool | None = None
    load_shedding: bool | None = None
    non_backup_loads: bool | None = None
    battery_label: str | None = None


class ConstantsBody(BaseModel):
    """Automation constants. Each optional; only sent fields are updated."""
    min_discharge_soc: float | None = Field(default=None, ge=0, le=100)
    max_charge_soc: float | None = Field(default=None, ge=0, le=100)
    demand_charge_min_soc: float | None = Field(default=None, ge=0, le=100)
    battery_capacity_kwh: float | None = Field(default=None, ge=0, le=1000)
    battery_max_power_kw: float | None = Field(default=None, ge=0, le=100)
    default_operating_mode: str | None = Field(default=None, pattern=r"^(self|tou|backup)$")


class TariffValidateReq(BaseModel):
    pricing: dict | None = None


class GatewayScanReq(BaseModel):
    subnet: str | None = None


class HaTestReq(BaseModel):
    base_url: str
    token: str | None = None
    # Editing an existing instance sends a blank token (tokens are never returned
    # to the client), so pass the id and the probe falls back to the STORED token
    # instead of testing unauthenticated and reporting a bogus 401.
    ha_id: str | None = None


class NotifyDeviceCreate(BaseModel):
    alias: str
    instance_id: str
    service: str
    enabled: bool = True


class NotifyDeviceUpdate(BaseModel):
    alias: str | None = None
    instance_id: str | None = None
    service: str | None = None
    enabled: bool | None = None


class NotifyTestReq(BaseModel):
    # Either an existing device id, or an ad-hoc instance+service so a device can
    # be tested BEFORE it is saved — which is the point of testing it.
    device_id: str | None = None
    instance_id: str | None = None
    service: str | None = None
    title: str = "FranklinWH Direct Connect Bridge"
    message: str = "Test notification — if you can read this, this device works."



class BatteryCmdReq(BaseModel):
    # One control from the Battery Control widget, mirroring the Modbus bridge's
    # per-slug command model: slug (battery_command / battery_command_power /
    # _power_pct / _duration / _target_soc) + its value.
    slug: str
    value: str = ""


class ConditionEvalReq(BaseModel):
    # An unsaved condition tree from the editor. `conditions` mixes leaf rows and
    # nested {match, conditions} groups; raw dicts, validated by the evaluator.
    match: str = "all"
    conditions: list[dict] = []


class NotifyBroadcastReq(BaseModel):
    # Send one message to many saved devices at once. device_ids=None → every
    # ENABLED device; an explicit list targets exactly those (enabled or not).
    title: str = "FranklinWH Direct Connect Bridge"
    message: str
    device_ids: list[str] | None = None

class ScheduleReq(BaseModel):
    name: str
    enabled: bool = True
    fire_at: str = "00:00"              # HH:MM
    duration_min: int = 0
    match: str = "all"                  # all | any
    entry_hold_s: int = 0               # dwell: conditions must hold this long (s)
    # Which gateway a battery action targets. "" / None = the default gateway.
    # Ignored for a notify-only schedule, which touches no gateway at all.
    gateway_id: str = ""
    conditions: list[dict] = Field(default_factory=list)
    # Optional "end early when…" gate: a (flat) condition list that closes the window
    # early when it becomes true — releasing a force dispatch + firing exit HA actions.
    exit_conditions: list[dict] = Field(default_factory=list)
    exit_match: str = "all"
    # Calendar recurrence — every field is a restriction; empty/None = no restriction
    # (fires every day, the legacy behaviour). days: 0=Mon…6=Sun. one-off = start==end.
    days: list[int] = Field(default_factory=list)
    months: list[int] = Field(default_factory=list)
    day_of_month: int | None = None
    start_date: str | None = None
    end_date: str | None = None
    # Orchestration: when several schedules fire the same tick for the same gateway,
    # the highest priority wins; the rest are deferred for the day. Default 0.
    priority: int = 0
    # What to do if the battery is already under ANOTHER schedule's dispatch:
    # override (take control) | defer (skip for the day) | wait (retry next tick).
    conflict: str = "override"
    # Trigger model. Absent/'daily' = the legacy single fire_at+duration window.
    # window: multiple `windows` [{start,end}] | once: a single date (start_date==end_date)
    # weekly: days+time | monthly: day_of_month+months | interval: every interval_min from
    # `anchor` | cron: `cron` expr | always: gated purely by entry conditions.
    trigger_type: str = "daily"
    windows: list[dict] = Field(default_factory=list)
    interval_min: int = 0
    anchor: str = ""
    cron: str = ""
    action: dict = Field(default_factory=dict)
    ha_actions: list[dict] = Field(default_factory=list)


class ScheduleImportReq(BaseModel):
    type: str | None = None
    version: int | None = None
    entries: list[dict] = Field(default_factory=list)


class HaExposeReq(BaseModel):
    instance_id: str
    entity_id: str
    exposed: bool


class RawCmdReq(BaseModel):
    cmd: int
    # Bare dict on purpose: this is a verbatim passthrough, so the dataArea must not
    # be coerced, validated or reordered on its way to the wire.
    # None = "not supplied, use the command's read payload"; {} = "send an EMPTY
    # dataArea" and must be honoured verbatim. Conflating them sent opt:1 when the
    # user explicitly chose no-opt.
    data: dict | None = None
    confirm: bool = False               # required for any non-read (opt != 0)


class GenEnableReq(BaseModel):
    enabled: bool


class GenSocReq(BaseModel):
    start_below: int
    stop_above: int


class GeneratorModeReq(BaseModel):
    mode: str                           # "auto" | "manual"


class ReserveReq(BaseModel):
    # Accept a friendly mode name (self/tou/backup) OR the cloud workMode int; and soc OR
    # the cloud-aligned requestedSOC. UI sends {mode, soc}; cloud-facade callers may send the
    # workMode/requestedSOC pair.
    mode: str | None = None
    soc: int | None = None
    requestedSOC: int | None = None
    workMode: int = 0
    electricityType: int = 1


# -- live settings-write (P7) -------------------------------------------------
# Only these runtime-applicable fields are editable via PUT /api/settings; restart-only
# fields (broker / host / poll_interval / metrics) stay read-only. log_level maps an
# HA-style level name to a python logging level applied live to the bridge logger.
class BmsRecordReq(BaseModel):
    """Start a BMS recording session. Defined at module scope — a model nested in
    create_app() cannot have its forward reference resolved by FastAPI."""
    samples: int = 20
    interval_s: float = 15.0
    id: int = 1
    label: str | None = None


class SettingsUpdate(BaseModel):
    allow_writes: bool | None = None
    log_level: str | None = None
    ha_notify: bool | None = None
    ha_url: str | None = None           # standalone HA base URL (add-on uses Supervisor token)
    ha_token: str | None = None         # standalone long-lived access token (write-only)
    # Cloud reserve-control credentials (HYBRID P3). Reserve SoC is cloud-owned — the
    # local API accepts the write, echoes the value back, and discards it — so these
    # are the only way to set it. Password is WRITE-ONLY: GET reports password_set.
    fwh_cloud_email: str | None = None
    fwh_cloud_password: str | None = None
    fwh_cloud_gateway: str | None = None
    # Location + PV array for the Open-Meteo solar/weather forecast.
    pv_latitude: float | None = None
    pv_longitude: float | None = None
    pv_kwp: float | None = None
    pv_tilt: float | None = None
    pv_azimuth: float | None = None
    nem_region: str | None = None
    tariff_price_entity: str | None = None
    tariff_feedin_entity: str | None = None
    billing_dynamic: bool | None = None       # AEMO NEM wholesale spot region
    # Interrupted scheduled-dispatch policy: none | notify | release | resume.
    dispatch_interrupt_policy: str | None = None


_LOG_LEVELS = {
    "trace": logging.DEBUG, "debug": logging.DEBUG, "info": logging.INFO,
    "notice": logging.INFO, "warning": logging.WARNING, "error": logging.ERROR,
    "fatal": logging.CRITICAL,
}


# Cloud workMode → local set_mode alias (resolved via scheduling_type in the library).
_CLOUD_WORKMODE_ALIAS = {1: "tou", 2: "self", 3: "backup"}

# Cloud requestedOperatingMode aliases (mirrors franklinwh-cloud modes.py) → workMode.
_CLOUD_MODE_ALIASES = {
    "1": 1, "time_of_use": 1, "timeofuse": 1, "tou": 1,
    "tou_battery_import": 1, "tou_battery_export": 1, "tou_custom": 1, "tou_json": 1,
    "2": 2, "self_consumption": 2, "selfconsumption": 2, "self": 2, "sc": 2,
    "3": 3, "emergency_backup": 3, "emergencybackup": 3, "emergency": 3, "backup": 3,
}

# Cloud GridStatus names/values (franklinwh_cloud.models.GridStatus), mirrored so the
# facade has no runtime dependency on franklinwh-cloud. NORMAL=0 / DOWN=1 / OFF=OFF_GRID=2.
_GRID_STATUS = {"normal": 0, "down": 1, "off": 2, "off_grid": 2, "offgrid": 2}


def _resolve_cloud_mode(requested) -> tuple[str, int | None]:
    """Map a cloud requestedOperatingMode to (local_mode, workMode). A cloud workMode
    (1/2/3) or cloud alias resolves to the tou/self/backup alias the local set_mode
    understands; anything else passes through unchanged (site id / tariff name)."""
    key = str(requested).strip().lower().replace(" ", "_").replace("-", "_")
    wm = _CLOUD_MODE_ALIASES.get(key)
    if wm is not None:
        return _CLOUD_WORKMODE_ALIAS[wm], wm
    return str(requested), None


def _grid_status_value(status) -> int:
    """Resolve a cloud GridStatus (name NORMAL/DOWN/OFF or value 0/1/2) to its int."""
    key = str(status).strip().lower().replace(" ", "_").replace("-", "_")
    if key in _GRID_STATUS:
        return _GRID_STATUS[key]
    if key.lstrip("-").isdigit() and int(key) in (0, 1, 2):
        return int(key)
    raise ValueError(f"unknown grid status {status!r}; expected NORMAL/DOWN/OFF (or 0/1/2)")


def create_app() -> FastAPI:
    # Capture the bridge logger's INFO+ records into an in-memory ring buffer so the
    # Logs tab / GET /api/logs can serve them (idempotent — safe across create_app calls).
    logbuffer.install("franklinwh_direct_connect_bridge", level=logging.INFO)
    # Persist logs to the SQLite store (durable, queryable, paginated) rather than a
    # rewritten JSONL file. Import any legacy file once, then hydrate from the DB.
    try:
        _logs_store = db.get_store(get_settings())
        if _logs_store is not None:
            logbuffer.set_store(_logs_store)
            logbuffer.import_jsonl_once()
            logbuffer.hydrate_from_store()
    except Exception:  # noqa: BLE001 — logging setup must never block startup
        pass
    _log_disclaimer_once()   # stamp the unofficial-app disclaimer into the (durable) log
    try:  # first-run install date (for the support bundle) — set once, never overwritten
        _cfg_store = db.get_store(get_settings())
        if _cfg_store is not None and not _cfg_store.get_config("install_date"):
            import datetime as _idt
            _cfg_store.set_config("install_date",
                                  _idt.datetime.now(_idt.timezone.utc).strftime("%Y-%m-%d"))
        if _cfg_store is not None:
            _cfg_store.record_version(__version__, _asset_version())   # update history
    except Exception:  # noqa: BLE001
        pass

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        s = get_settings()
        # Zero-config MQTT: fill unset broker creds from the HA Supervisor before the
        # poller (and MqttPublisher) start. Runs in a thread with a short timeout so a
        # hung network call can never block startup; never raises.
        await asyncio.to_thread(apply_supervisor_mqtt, s)
        # Apply the persisted Modbus (SunSpec 502) master switch — default on. When the
        # user disabled it from the Control tab, ratings + force dispatch stay off.
        try:
            _mstore = db.get_store(s)
            if _mstore is not None:
                from . import battery_control as _bc
                _bc.set_enabled(_mstore.get_config("modbus_enabled", "1") != "0")
                try:
                    _bc.set_host_override(_mstore.get_config("modbus_host_override", "") or "",
                                          int(_mstore.get_config("modbus_port_override", "0") or 0))
                except Exception:  # noqa: BLE001
                    pass
        except Exception:  # noqa: BLE001 — never block startup on a config read
            pass
        # Build the gateway registry. DB-backed roster when the metrics store is
        # present (seeded once from FWH_HOSTS so existing installs are unchanged), else
        # the env path. A single-gateway setup registers exactly one entry, so the roster
        # + every existing endpoint behave exactly as before.
        env_entries = gateway_list(s) or ([(s.fwh_host, s.fwh_host)] if s.fwh_host else [])
        store = db.get_store(s)
        db_rows: list = []
        if store is not None:
            try:
                store.seed_gateways(env_entries)
                store.ensure_default_site_meter()   # default Home site + Meter 1; attach gateways
                db_rows = store.gateways()
            except Exception:  # noqa: BLE001 — roster must never block startup
                db_rows = []
        if db_rows:
            for r in db_rows:
                if not r.get("enabled"):
                    continue
                if r.get("is_mock"):
                    seed = mockgw.seed_for(r["id"], r.get("mock_seed"))
                    host = mockgw.start_mock(r["id"], seed=seed,
                                             units=int(r.get("mock_units") or 1))
                    state.register_gateway(r["id"], host, r.get("label"), is_mock=True,
                                           publish_ha=bool(r.get("publish_ha")))
                else:
                    state.register_gateway(r["id"], r.get("host", ""), r.get("label"),
                                           port=int(r.get("port") or 9000),
                                           publish_ha=bool(r.get("publish_ha")))
        else:
            for host, label in env_entries:
                state.register_gateway(host, host, label)
        if s.mqtt_enabled or metrics_active(s):
            gws = state.gateways()
            log.info("starting %d poller(s) (mqtt=%s, metrics=%s)",
                     len(gws), s.mqtt_enabled, metrics_active(s))
            for gw in gws:
                await supervisor.start_poller(s, gw)
        # VPP dispatch monitor: DETECT (never auto-release) a battery force dispatch —
        # log start/stop, and on boot raise a CRITICAL orphan alert if one was left
        # active (respects the two-masters rule; the user releases via the top nav).
        # Off-thread so a slow/unreachable aGate Modbus never delays startup.
        def _vpp_loop():
            import time as _t
            from . import vpp_monitor, battery_control
            _host = lambda: (os.environ.get("FWH_MODBUS_HOST")
                             or (state.gateways()[0].active_host if state.gateways() else None))
            def _store():
                try:
                    return db.get_store(get_settings())
                except Exception:  # noqa: BLE001
                    return None
            if os.environ.get("FWH_VPP_MONITOR", "1") not in ("1", "true", "yes", "on"):
                return
            try:
                interval = max(15, int(os.environ.get("FWH_VPP_MONITOR_S", "60")))
            except ValueError:
                interval = 60
            boot = True
            while True:
                try:
                    h, st = _host(), _store()
                    if h and st and battery_control.available()[0]:
                        reconciled = []
                        if boot:
                            # Reconcile scheduled dispatches a restart left in-flight,
                            # per the user's policy, BEFORE the generic orphan check —
                            # so our own dispatch is not also flagged as an orphan.
                            try:
                                policy = getattr(get_settings(),
                                                 "dispatch_interrupt_policy", "notify")
                                def _rsoc():
                                    try:
                                        gw = state.gateways()[0] if state.gateways() else None
                                        return (getattr(gw, "last_state", {}) or {}).get("soc") if gw else None
                                    except Exception:  # noqa: BLE001
                                        return None
                                reconciled = battery_control.reconcile_interrupted(
                                    st, h, policy, soc_getter=_rsoc,
                                    notify=lambda t, m: vpp_monitor._notify_devices(st, t, m))
                                for r in reconciled:
                                    log.warning("dispatch reconcile [%s]: %s",
                                                r.get("action"), r.get("detail"))
                            except Exception as e:  # noqa: BLE001
                                log.error("dispatch reconcile failed: %s", e)
                        # Skip the generic boot-orphan alert if we already handled a
                        # scheduled dispatch this boot (avoids double-notifying).
                        _res = vpp_monitor.check(h, st, boot=(boot and not reconciled))
                        # Record the VPP/force truth (Modbus M704 — the aGate 1301
                        # run_status never shows VPP) on the matching gateway, for the
                        # top-nav + dashboard badge.
                        try:
                            for _gw in state.gateways():
                                if _gw.active_host == h:
                                    _gw.vpp_active = _res.get("vpp")
                                    break
                        except Exception:  # noqa: BLE001
                            pass
                except Exception as e:  # noqa: BLE001
                    log.debug("VPP monitor pass failed: %s", e)
                boot = False
                _t.sleep(interval)
        import threading as _th
        _th.Thread(target=_vpp_loop, daemon=True).start()

        # Cloud run-status / VPP: the ONLY source that can tell a genuine VPP from a local
        # force (see FEAT-VPP-CLOUD-RUNSTATUS). Slow cadence + the providers auth breaker so a
        # bad login never locks the account; a transport error just leaves the last value and
        # the UI falls back to the Modbus FORCE signal.
        def _cloud_status_loop():
            import time as _t
            from . import cloud_status
            s0 = get_settings()
            if not (s0.fwh_cloud_email and s0.fwh_cloud_password):
                return
            if os.environ.get("FWH_CLOUD_STATUS", "1") not in ("1", "true", "yes", "on"):
                return
            try:
                interval = max(120, int(os.environ.get("FWH_CLOUD_STATUS_S", "300")))
            except ValueError:
                interval = 300
            retry = min(interval, 45)   # the cloud link is flaky (HTTP/2 resets) — on a
            _t.sleep(8)                 # failed read, retry soon rather than after `interval`
            want = (get_settings().fwh_cloud_gateway or "").upper()
            _last_status = None   # only log cloud status on a real CHANGE (see Logs policy)
            _fail_streak = 0      # for failure VISIBILITY without 5-min spam (onset + recovery)
            while True:
                ok = False
                try:
                    data = cloud_status.poll(get_settings())
                    if data is not None:
                        ok = True
                        # Store on the gateway matching the cloud serial, else the primary.
                        gws = state.gateways()
                        target = next((g for g in gws
                                       if (g.serial or "").upper() == want), None) \
                            or (gws[0] if gws else None)
                        if target is not None:
                            target.cloud_vpp = bool(data["is_vpp"])
                            target.cloud_mode = data.get("effective_mode") or ""
                            target.cloud_programme = data.get("programme")
                            target.cloud_ts = data["ts"]
                            # Log ONLY a real state change — not every 5-min poll (matches the
                            # Logs policy: startup, state changes and errors). A transient unknown
                            # (empty mode -> "?") is skipped so it can't flap the log.
                            mode = data.get("effective_mode") or ""
                            if mode:
                                key = (mode, bool(data["is_vpp"]))
                                if key != _last_status:
                                    _last_status = key
                                    log.info("cloud status: %s%s", mode,
                                             " (VPP)" if data["is_vpp"] else "")
                except Exception as e:  # noqa: BLE001 — never let this loop die
                    log.debug("cloud status loop pass failed: %s", e)
                # Failure VISIBILITY for troubleshooting: the first failure (and the recovery)
                # is WARNING/INFO so a down cloud link shows at the normal level; subsequent
                # repeats stay DEBUG so a persistent outage can't spam the log every cycle.
                if ok:
                    if _fail_streak:
                        log.info("cloud link recovered after %d failed poll(s)", _fail_streak)
                        _fail_streak = 0
                else:
                    _fail_streak += 1
                    reason = cloud_status.LAST_ERROR or "cloud unreachable / auth error"
                    if _fail_streak == 1:
                        log.warning("cloud link failing — %s (will keep retrying every %ds)",
                                    reason, retry)
                    else:
                        log.debug("cloud link still failing (%d consecutive): %s", _fail_streak, reason)
                # Back off to the breaker's own cadence once it has locked, so we never hammer.
                if providers._cloud_auth.get("state") == "locked":
                    log.warning("cloud auth breaker LOCKED after repeated failures — cloud polling "
                                "stopped; re-enter FranklinWH credentials to clear it")
                    return
                _t.sleep(interval if ok else retry)
        _th.Thread(target=_cloud_status_loop, daemon=True).start()

        # ── L0 supervision (RUNTIME_DESIGN phase 0) ──────────────────────────
        # Phase 0 REGISTERS existing work rather than rewriting it, so the daemon
        # threads above appear here too — observable now, convertible to async
        # workers in phase 1 (decision 1). Until converted they report
        # restartable=False rather than offering a button that cannot work.
        for _name, _concern, _cadence, _cls in (
            ("vpp-monitor", "track VPP / force state", 60.0, _workers.RestartClass.FREE),
            ("cloud-status", "cloud witness and auth breaker", 300.0, _workers.RestartClass.FREE),
            ("dispatch-watchdog", "end forces at their deadline", 30.0,
             _workers.RestartClass.GUARDED),
        ):
            _w = _workers.registry.register(_workers.Worker(
                name=_name, concern=_concern, cadence_s=_cadence,
                restart_class=_cls, kind="thread"))
            _w.beat(state=_workers.WorkerState.RUNNING)

        _sup_stop = asyncio.Event()

        def _on_worker_transition(w, reason: str) -> None:
            # A worker dying is exactly the class of failure that used to pass
            # unnoticed, so it is audited like a consequential action.
            _audit("worker_failed", detail=w.name, result=reason, ok=False)

        _sup_worker = _workers.registry.register(_workers.Worker(
            name="supervisor", concern="watch every worker's liveness",
            cadence_s=5.0, restart_class=_workers.RestartClass.FREE, kind="task"))

        async def _supervisor_loop() -> None:
            while not _sup_stop.is_set():
                _sup_worker.beat(state=_workers.WorkerState.RUNNING)
                try:
                    _workers._supervise_once(_workers.registry,
                                             on_transition=_on_worker_transition)
                except Exception:  # noqa: BLE001 — must outlive its subjects
                    log.exception("supervisor pass failed")
                try:
                    await asyncio.wait_for(_sup_stop.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    pass

        _sup_task = asyncio.create_task(_supervisor_loop())
        _sup_worker._task = _sup_task
        log.info("worker supervision active (%d workers registered)",
                 len(_workers.registry.all()))
        try:
            yield
        finally:
            _sup_stop.set()
            _sup_task.cancel()
            # Release any dispatch WE are holding before the bridge stops — a running
            # bridge is the only thing that can release it (hardware timer is cosmetic).
            try:
                from . import battery_control
                cur = battery_control.current()
                if cur.get("active") not in (None, "Not Active"):
                    host = os.environ.get("FWH_MODBUS_HOST") or (
                        state.gateways()[0].active_host if state.gateways() else None)
                    if host:
                        log.warning("battery force: releasing %s on shutdown", cur["active"])
                        battery_control.execute("Release", host=host)
            except Exception as e:  # noqa: BLE001
                log.error("battery shutdown release failed: %s", e)
            await supervisor.stop_all()
            mockgw.stop_all()

    app = FastAPI(
        title="franklinwh-direct-connect-bridge", version=__version__,
        description=(
            "REST + MQTT bridge for the FranklinWH aGate local API.\n\n"
            "**UNOFFICIAL software — NOT affiliated with or endorsed by FranklinWH.** "
            "It talks to FranklinWH's undocumented Direct Connect (local) API and its cloud API - the "
            "same private API the official FranklinWH mobile app and FleetView installer portal use "
            "(intended for those apps, not third parties) - plus the standard SunSpec Modbus TCP API "
            "(with undocumented FranklinWH extensions). Any of these may change, break, or become "
            "unavailable without notice. Provided **AS-IS**, without warranty of any "
            "kind — use entirely at your own risk. **Do NOT contact FranklinWH support** about this app; "
            "raise issues, defects, or feature requests on GitHub: "
            "https://github.com/david2069/franklinwh-direct-connect-bridge/issues . MIT License."
        ),
        lifespan=lifespan)

    app.mount("/static",
              StaticFiles(directory=str(Path(__file__).parent / "static")),
              name="static")

    # The franklinwh-local library docs (mkdocs site), if bundled into the image by
    # tools/build_image.sh. Served at /guide (FastAPI owns /docs for Swagger). Skipped
    # cleanly in dev / when the site was not built.
    _docs_env = os.environ.get("FWH_DOCS_DIR")
    _docs_candidates = ([Path(_docs_env)] if _docs_env else []) + [
        Path(__file__).resolve().parents[2] / "docs_site",   # /app/docs_site in the image
        Path(__file__).resolve().parents[3] / "docs_site",
    ]
    for _d in _docs_candidates:
        if _d.is_dir() and (_d / "index.html").exists():
            app.mount("/guide", StaticFiles(directory=str(_d), html=True), name="guide")
            break

    # -- gateway resolvers (multi-gateway, Phase 2) --------------------------
    # No ``gateway`` param ⇒ the default (first-registered) gateway ⇒ exactly the
    # single-gateway behaviour. An unknown id ⇒ 404 (before any device I/O).
    def _gw_or_404(gateway: str | None) -> GatewayState:
        if gateway:
            gw = state.get_gateway(gateway)
            if gw is None:
                raise HTTPException(status_code=404,
                                    detail=f"unknown gateway {gateway!r}")
            return gw
        return get_state()   # default (lazily-created) gateway — single-gateway back-compat

    def _metrics_gw_key(gateway: str | None):
        """Metrics rows are tagged by gateway SERIAL (poller: gw.serial or gw.id). The UI
        passes a gateway id, so map id → serial before querying; pass-through if a serial
        (or None) was given so single-gateway and already-serial callers still work."""
        if not gateway:
            return None
        g = state.get_gateway(gateway)
        return g.serial if (g is not None and g.serial) else gateway

    def _gw_host(gateway: str | None) -> str:
        gw = _gw_or_404(gateway)
        return gw.active_host or gw.configured_host

    def _gateway_summary(gw: GatewayState) -> dict:
        """The poller's cached last-good summary when warm, else an on-demand read of
        this gateway's host. Shared by /api/summary and /api/gateways/{id}/summary."""
        summ = {**gw.last_summary, "cached": True} if gw.last_summary \
            else client.summary(get_settings(), host=gw.active_host)
        return _apply_capabilities(_apply_vpp(summ, gw))

    def _apply_capabilities(summ: dict) -> dict:
        """Advertise which subsystems are usable, so the UI can mark each control as needing
        Modbus (force dispatch, ratings, FORCE badge) or Cloud (reserve SoC, VPP mode) and
        GUARD it when that subsystem isn't configured/enabled/reachable."""
        s = get_settings()
        from . import battery_control, providers
        try:
            cloud_state = providers.cloud_auth_status().get("state")
        except Exception:  # noqa: BLE001
            cloud_state = "unknown"
        summ["capabilities"] = {
            "modbus_enabled": battery_control.is_enabled(),
            "modbus_reachable": bool(summ.get("modbus_502")),
            "cloud_configured": bool(s.fwh_cloud_email and s.fwh_cloud_password),
            # usable = configured AND the breaker hasn't rejected the creds / locked out
            "cloud_available": bool(s.fwh_cloud_email and s.fwh_cloud_password)
                               and cloud_state not in ("locked", "invalid", "unconfigured"),
            "cloud_state": cloud_state,
        }
        return summ

    def _apply_vpp(summ: dict, gw: GatewayState) -> dict:
        """Overlay the dispatch state onto a summary's power block. The aGate's 1301 run_status
        never reports a dispatch, so this is the source of truth for the badge: cloud-confirmed
        VPP ("vpp" + programme + effective_mode label) wins over the Modbus M704 FORCE state
        ("force"). Off-grid still comes from run_status (correct)."""
        import time as _t
        from . import cloud_status
        kind, programme = _dispatch_kind(gw)
        cloud_fresh = (gw.cloud_vpp is not None
                       and (_t.time() - (gw.cloud_ts or 0)) < cloud_status.STALE_AFTER_S)
        if kind is None and gw.vpp_active is None and not cloud_fresh:
            return summ
        power = dict(summ.get("power") or {})
        power["vpp"] = kind is not None
        power["vpp_kind"] = kind                          # "vpp" | "force" | None
        power["vpp_label"] = ("Force dispatch" if kind == "force"
                              else (gw.cloud_mode or "VPP mode") if kind == "vpp" else None)
        power["vpp_programme"] = programme
        # The cloud's app-matching operating-mode label, when a fresh read exists.
        power["effective_mode"] = (gw.cloud_mode or None) if cloud_fresh else None
        return {**summ, "power": power}

    @app.get("/api/live")
    def api_live():
        """Liveness probe for the container HEALTHCHECK / HA watchdog. Confirms the web
        app is serving — deliberately does NO device I/O, so an unreachable aGate does
        NOT mark the container unhealthy (the bridge stays up by design when the gateway
        is down). Use /api/health for actual gateway reachability."""
        return {"status": "ok", "service": "franklinwh-direct-connect-bridge", "version": __version__}

    @app.get("/api/providers")
    def api_providers():
        """Hybrid capability report (HYBRID-CAPABILITIES Phase 1): which local hard walls
        (battery dispatch, reserve/cloud writes) are fillable, and via which provider — an
        installed sibling bridge's REST or a fallback library. Detection only (no writes
        yet). Runs short health probes; never 500s."""
        try:
            return providers.capabilities(get_settings())
        except Exception as e:  # noqa: BLE001 — detection must never 500
            return {"error": str(e)}

    @app.get("/api/health")
    def api_health(gateway: str | None = Query(None)):
        return client.health(get_settings(), host=_gw_host(gateway))

    @app.get("/api/summary")
    def api_summary(gateway: str | None = Query(None)):
        # Serve the poller's cached last-good summary when warm — avoids a full device
        # session (login + 4 cmdType reads) on every 5 s browser poll, which over flaky
        # wifi caused the operating-mode section to flicker + slow first load. The cache
        # carries last-good values + the CURRENT ok/stale status; a cold cache (no poller)
        # falls back to a fresh read. ``gateway`` selects the gateway; None → default
        # (single-gateway behaviour unchanged).
        return _gateway_summary(_gw_or_404(gateway))

    # -- multi-gateway roster (reads / monitoring, Phase 1) -------------------
    # Control / cmd / cloud writes + MQTT endpoints remain on the DEFAULT gateway
    # (get_state()) in Phase 1 — per-gateway writes are Phase 2.
    def _gw_store():
        # Never let a broken/absent store 500 the roster — fall back to the
        # registered-gateway view (env path) when the store can't be opened.
        try:
            return db.get_store(get_settings())
        except Exception:  # noqa: BLE001
            return None

    def _gw_merged(row: dict) -> dict:
        """A roster row = DB config + live poller state (when the gateway is registered)."""
        gw = state.get_gateway(row["id"])
        base = _roster_entry(gw) if gw is not None else {
            "id": row["id"], "label": row.get("label"), "host": row.get("host"),
            "configured_host": row.get("host"), "serial": None, "firmware": None,
            "ok": False, "stale": False, "soc": None, "mode": None,
            "mqtt_connected": False, "cached": False, "updated": False,
        }
        base.update({
            "label": row.get("label") or base.get("label"),
            "port": row.get("port"),
            "enabled": bool(row.get("enabled")),
            "is_mock": bool(row.get("is_mock")),
            "mock_units": row.get("mock_units"),
            "publish_ha": bool(row.get("publish_ha")),
            "is_default": bool(row.get("is_default")),
            "meter_id": row.get("meter_id"),
            "description": row.get("description") or "",
            "model": "aGate (mock)" if row.get("is_mock") else (base.get("model_detail") or "aGate"),
            "running": supervisor.is_running(row["id"]),
        })
        return base

    @app.get("/api/gateways")
    def api_gateways():
        """Roster: one row per gateway. DB-backed (includes disabled rows) when the
        metrics store is present, else the registered-gateway view. Never 500s."""
        st = _gw_store()
        if st is not None:
            rows = st.gateways()
            if rows:
                return [_gw_merged(r) for r in rows]
        gws = state.gateways() or [get_state()]
        return [_roster_entry(gw) for gw in gws]

    async def _reconcile_gateway(row: dict) -> None:
        """Bring the live poller + mock emulator in line with a roster row's enabled/
        mock/units state. Tear down first, then (re)start if it should be polling."""
        gid = row["id"]
        s = get_settings()
        want_poll = s.mqtt_enabled or metrics_active(s)
        await supervisor.stop_poller(gid)
        state.unregister_gateway(gid)
        if not row.get("enabled") or not want_poll:
            if row.get("is_mock"):
                mockgw.stop_mock(gid)
            return
        if row.get("is_mock"):
            mockgw.stop_mock(gid)   # fresh emulator (unit count may have changed)
            seed = mockgw.seed_for(gid, row.get("mock_seed"))
            host = mockgw.start_mock(gid, seed=seed, units=int(row.get("mock_units") or 1))
            gw = state.register_gateway(gid, host, row.get("label"), is_mock=True,
                                        publish_ha=bool(row.get("publish_ha")))
        else:
            gw = state.register_gateway(gid, row.get("host", ""), row.get("label"),
                                        port=int(row.get("port") or 9000),
                                        publish_ha=bool(row.get("publish_ha")))
        await supervisor.start_poller(s, gw)

    @app.post("/api/gateways", status_code=201)
    async def api_gateway_create(req: GatewayCreate):
        _guard_writes()
        st = _gw_store()
        if st is None:
            raise HTTPException(503, "metrics store is disabled; gateway roster needs it")
        import uuid
        gid = uuid.uuid4().hex[:12]
        seed = mockgw.seed_for(gid, req.mock_seed) if req.is_mock else None
        row = st.create_gateway(
            gw_id=gid, label=req.label, host=("127.0.0.1" if req.is_mock else req.host),
            port=req.port, is_default=req.is_default, enabled=req.enabled,
            is_mock=req.is_mock, mock_seed=seed, mock_units=req.mock_units,
            publish_ha=req.publish_ha, description=req.description)
        await _reconcile_gateway(row)
        return _gw_merged(row)

    @app.patch("/api/gateways/{gw_id}")
    async def api_gateway_update(gw_id: str, req: GatewayUpdate):
        _guard_writes()
        st = _gw_store()
        if st is None:
            raise HTTPException(503, "metrics store is disabled; gateway roster needs it")
        if st.gateway(gw_id) is None:
            raise HTTPException(404, f"no gateway '{gw_id}'")
        row = st.update_gateway(gw_id, **req.model_dump(exclude_unset=True))
        await _reconcile_gateway(row)
        return _gw_merged(row)

    @app.delete("/api/gateways/{gw_id}")
    async def api_gateway_delete(gw_id: str):
        _guard_writes()
        st = _gw_store()
        if st is None:
            raise HTTPException(503, "metrics store is disabled; gateway roster needs it")
        if st.gateway(gw_id) is None:
            raise HTTPException(404, f"no gateway '{gw_id}'")
        await supervisor.stop_poller(gw_id)
        mockgw.stop_mock(gw_id)
        state.unregister_gateway(gw_id)
        st.delete_gateway(gw_id)
        return {"ok": True, "id": gw_id}

    # ── sites + meters (Phase 1: multi-site / multi-meter roster) ─────────────
    _AC_TYPES = ("single", "split", "three")

    @app.get("/api/sites")
    def api_sites():
        st = _gw_store()
        if st is None:
            raise HTTPException(503, "metrics store is disabled; the sites roster needs it")
        return {"sites": st.sites()}

    @app.post("/api/sites", status_code=201)
    def api_site_create(req: SiteCreate):
        _guard_writes()
        st = _gw_store()
        if st is None:
            raise HTTPException(503, "metrics store is disabled")
        import uuid
        return st.create_site(sid="site_" + uuid.uuid4().hex[:8], **req.model_dump())

    @app.patch("/api/sites/{sid}")
    def api_site_update(sid: str, req: SiteUpdate):
        _guard_writes()
        st = _gw_store()
        if st is None or st.site(sid) is None:
            raise HTTPException(404, f"no site '{sid}'")
        return st.update_site(sid, **req.model_dump(exclude_unset=True))

    @app.delete("/api/sites/{sid}")
    def api_site_delete(sid: str):
        _guard_writes()
        st = _gw_store()
        if st is None or st.site(sid) is None:
            raise HTTPException(404, f"no site '{sid}'")
        if st.meters(site_id=sid):
            raise HTTPException(409, "site has meters — move or delete them first")
        st.delete_site(sid)
        return {"ok": True, "id": sid}

    @app.get("/api/meters")
    def api_meters(site: str | None = Query(None)):
        st = _gw_store()
        if st is None:
            raise HTTPException(503, "metrics store is disabled; the meters roster needs it")
        return {"meters": st.meters(site_id=site)}

    @app.post("/api/meters", status_code=201)
    def api_meter_create(req: MeterCreate):
        _guard_writes()
        st = _gw_store()
        if st is None:
            raise HTTPException(503, "metrics store is disabled")
        if st.site(req.site_id) is None:
            raise HTTPException(422, f"no site '{req.site_id}'")
        if req.ac_type not in _AC_TYPES:
            raise HTTPException(422, f"ac_type must be one of {', '.join(_AC_TYPES)}")
        import uuid
        return st.create_meter(mid="meter_" + uuid.uuid4().hex[:8], **req.model_dump())

    @app.patch("/api/meters/{mid}")
    def api_meter_update(mid: str, req: MeterUpdate):
        _guard_writes()
        st = _gw_store()
        if st is None or st.meter(mid) is None:
            raise HTTPException(404, f"no meter '{mid}'")
        body = req.model_dump(exclude_unset=True)
        if body.get("ac_type") and body["ac_type"] not in _AC_TYPES:
            raise HTTPException(422, f"ac_type must be one of {', '.join(_AC_TYPES)}")
        return st.update_meter(mid, **body)

    @app.delete("/api/meters/{mid}")
    def api_meter_delete(mid: str):
        _guard_writes()
        st = _gw_store()
        if st is None or st.meter(mid) is None:
            raise HTTPException(404, f"no meter '{mid}'")
        attached = [g for g in st.gateways() if g.get("meter_id") == mid]
        if attached:
            raise HTTPException(409, f"{len(attached)} gateway(s) connect to this meter — "
                                     "reassign them first")
        st.delete_meter(mid)
        return {"ok": True, "id": mid}

    # ── utilities + tariffs ────────────────────────────────────────────────────
    @app.get("/api/utilities")
    def api_utilities():
        st = _gw_store()
        if st is None:
            raise HTTPException(503, "metrics store is disabled")
        return {"utilities": st.utilities()}

    @app.post("/api/utilities", status_code=201)
    def api_utility_create(req: UtilityCreate):
        _guard_writes()
        st = _gw_store()
        if st is None:
            raise HTTPException(503, "metrics store is disabled")
        import uuid
        body = req.model_dump()
        return st.create_utility(uid="util_" + uuid.uuid4().hex[:8], name=body.pop("name", ""), **body)

    @app.patch("/api/utilities/{uid}")
    def api_utility_update(uid: str, req: UtilityUpdate):
        _guard_writes()
        st = _gw_store()
        if st is None or st.utility(uid) is None:
            raise HTTPException(404, f"no utility '{uid}'")
        return st.update_utility(uid, **req.model_dump(exclude_unset=True))

    @app.delete("/api/utilities/{uid}")
    def api_utility_delete(uid: str):
        _guard_writes()
        st = _gw_store()
        if st is None or st.utility(uid) is None:
            raise HTTPException(404, f"no utility '{uid}'")
        if st.tariffs(utility_id=uid):
            raise HTTPException(409, "utility has tariffs — delete them first")
        st.delete_utility(uid)
        return {"ok": True, "id": uid}

    @app.get("/api/tariffs")
    def api_tariffs(utility: str | None = Query(None)):
        st = _gw_store()
        if st is None:
            raise HTTPException(503, "metrics store is disabled")
        return {"tariffs": st.tariffs(utility_id=utility)}

    @app.post("/api/tariffs", status_code=201)
    def api_tariff_create(req: TariffCreate):
        _guard_writes()
        st = _gw_store()
        if st is None:
            raise HTTPException(503, "metrics store is disabled")
        if st.utility(req.utility_id) is None:
            raise HTTPException(422, f"no utility '{req.utility_id}'")
        import uuid
        body = req.model_dump()
        return st.create_tariff(tid="tariff_" + uuid.uuid4().hex[:8],
                                utility_id=body.pop("utility_id"), name=body.pop("name", ""),
                                billing_cycle_day=body.pop("billing_cycle_day", 1),
                                plan_version=body.pop("plan_version", ""), **body)

    @app.patch("/api/tariffs/{tid}")
    def api_tariff_update(tid: str, req: TariffUpdate):
        _guard_writes()
        st = _gw_store()
        if st is None or st.tariff(tid) is None:
            raise HTTPException(404, f"no tariff '{tid}'")
        return st.update_tariff(tid, **req.model_dump(exclude_unset=True))

    @app.delete("/api/tariffs/{tid}")
    def api_tariff_delete(tid: str):
        _guard_writes()
        st = _gw_store()
        if st is None or st.tariff(tid) is None:
            raise HTTPException(404, f"no tariff '{tid}'")
        st.delete_tariff(tid)
        return {"ok": True, "id": tid}

    @app.post("/api/tariffs/validate")
    def api_tariff_validate(req: TariffValidateReq):
        """Check a rate model's coverage/tier completeness — the editor's live linter."""
        from . import rate_model
        pricing = req.pricing or {}
        if pricing.get("kind") == "dynamic":
            # A dynamic/wholesale tariff carries no static rates — the live provider supplies
            # them. Validate the provider instead of demanding seasons/default_rate.
            dyn = pricing.get("dynamic") or {}
            probs = []
            if dyn.get("source") == "nem" and not (dyn.get("region") or "").strip():
                probs.append("Choose a NEM region for the AusNEM provider.")
            elif dyn.get("source") == "ha" and not (dyn.get("buy_entity") or "").strip():
                probs.append("Choose a buy price entity for the Home Assistant provider.")
            elif dyn.get("source") not in ("nem", "ha"):
                probs.append("Choose a wholesale provider (AusNEM or Home Assistant).")
            return {"ok": not probs, "problems": probs}
        problems = rate_model.validate(pricing.get("seasons"), pricing.get("default_rate"))
        return {"ok": not problems, "problems": problems}

    # ── tariff-profile interchange with the Modbus bridge (FEAT-IMPORT-AGL-SETUP) ──
    @app.get("/api/tariffs/{tid}/export")
    def api_tariff_export(tid: str):
        """Export one tariff (+ its utility + the meter's timezone) as a Modbus-compatible
        ``franklinwh-bridge/tariff-profile`` bundle — the exact shape the Modbus bridge reads."""
        from . import tariff_io
        st = _ha_store()
        tar = st.tariff(tid) if st else None
        if not tar:
            raise HTTPException(status_code=404, detail="no such tariff")
        util = st.utility(tar.get("utility_id")) if tar.get("utility_id") else None
        tz = ""
        try:
            tz = next((m.get("timezone") for m in st.meters() if m.get("tariff_id") == tid), "") or ""
        except Exception:  # pragma: no cover
            tz = ""
        return tariff_io.from_local(util, tar, tz)

    @app.post("/api/tariffs/import")
    def api_tariff_import(req: TariffProfileImport, dry_run: bool = Query(False)):
        """Import a Modbus ``franklinwh-bridge/tariff-profile`` — creates the utility + tariff
        and attaches them to the default meter (with the profile's timezone). dry_run previews."""
        from . import tariff_io
        if req.type and req.type != tariff_io.PROFILE_TYPE:
            raise HTTPException(
                status_code=400,
                detail=(f"unexpected bundle type '{req.type}' — this importer reads "
                        f"'{tariff_io.PROFILE_TYPE}' (a Modbus-bridge tariff export)."))
        util_f, tar_f, tz = tariff_io.to_local(req.profile or {})
        if dry_run:
            pr = tar_f.get("pricing") or {}
            return {"preview": {
                "retailer": util_f["name"], "network": util_f["network_dnsp"],
                "plan_type": util_f["plan_type"], "tariff_name": tar_f["name"],
                "billing_cycle_day": tar_f["billing_cycle_day"], "timezone": tz,
                "seasons": len(pr.get("seasons") or []),
                "fixed_charges": len(tar_f.get("fixed_charges") or []),
                "has_demand": bool(tar_f.get("demand_window")),
                "has_export_bonus": bool(tar_f.get("bonus_window")),
                "has_export_charge": bool(tar_f.get("charge_window"))}}
        _guard_writes()
        st = _ha_store()
        import uuid
        uid = "util_" + uuid.uuid4().hex[:8]
        if req.effective_start:
            util_f["effective_start"] = req.effective_start
        st.create_utility(uid=uid, name=util_f.pop("name"), **util_f)
        tid = "tar_" + uuid.uuid4().hex[:8]
        st.create_tariff(tid=tid, utility_id=uid, name=tar_f.pop("name"),
                         billing_cycle_day=tar_f.pop("billing_cycle_day"), **tar_f)
        # attach to the default meter so it prices immediately
        attached = None
        try:
            meters = st.meters()
            mid = next((m["id"] for m in meters if m.get("is_default")),
                       (meters[0]["id"] if meters else None))
            if mid:
                upd = {"utility_id": uid, "tariff_id": tid}
                if tz:
                    upd["timezone"] = tz
                st.update_meter(mid, **upd)
                attached = mid
        except Exception:  # pragma: no cover
            attached = None
        return {"ok": True, "utility_id": uid, "tariff_id": tid, "attached_meter": attached}

    # ── Energy Costs / billing view (FEAT-BILLING-SERVICE) ────────────────────
    @app.get("/api/billing/overview")
    def api_billing_overview(gateway: str | None = Query(None)):
        """Live period-to-date billing for the gateway's meter's tariff: the running
        energy/demand/bonus/export-charge/fixed points + the retailer/tariff it prices
        against + billing-cycle progress. `configured:false` when no tariff is assigned."""
        from . import billing
        st = _ha_store()
        if st is None:
            return {"configured": False}
        read = billing.billing_read(st, gateway)
        fixed = billing.fixed_snapshot(st, gateway)
        if not read and not fixed:
            return {"configured": False}
        cfg = billing._billing_cfg(st, gateway)
        now = _dt.datetime.now()
        days = period_days = None
        if cfg:
            ps = billing._period_start(now, int(cfg.get("cycle_day", 1) or 1))
            pe = billing._period_end(ps, int(cfg.get("cycle_day", 1) or 1))
            days = round(max(0.0, (now - ps).total_seconds() / 86400.0), 2)
            period_days = round((pe - ps).total_seconds() / 86400.0, 2)
        out = {"configured": True, "meta": billing._period_meta(st, gateway),
               "cycle_day": (cfg or {}).get("cycle_day"), "days_elapsed": days,
               "period_days": period_days}
        out.update(read)
        out.update(fixed)
        # net cost so far = imports − credits + demand + export-charge + fixed − bonus
        out["net.period_cost"] = round(
            billing._num(out.get("energy.import_cost")) - billing._num(out.get("energy.export_credit"))
            + billing._num(out.get("demand.period_charge")) + billing._num(out.get("tariff.export_charge_cost"))
            + billing._num(out.get("fixed.accrued_period")) - billing._num(out.get("bonus.period_credit")), 2)
        # linear projection to end of period
        if days and period_days and days > 0:
            out["net.projected_cost"] = round(out["net.period_cost"] * period_days / days, 2)
        return out

    @app.get("/api/billing/history")
    def api_billing_history(gateway: str | None = Query(None),
                            limit: int = Query(60, ge=1, le=200), fmt: str = Query("json")):
        """Closed billing periods (newest first), or a CSV export with ?fmt=csv."""
        st = _ha_store()
        rows = st.billing_periods(limit=limit, gateway_id=gateway) if st else []
        if fmt == "csv":
            cols = ["period_start", "period_end", "retailer", "network", "tariff_name",
                    "import_kwh", "import_cost", "export_credit", "demand_peak_kw",
                    "demand_charge", "bonus_credit", "export_charge", "fixed_total", "net_total"]

            def _row(r):
                return ",".join("" if r.get(c) is None else str(r.get(c)) for c in cols)
            body = [",".join(cols)] + [_row(r) for r in rows]
            return PlainTextResponse("\n".join(body) + "\n", media_type="text/csv",
                                     headers={"Content-Disposition": "attachment; filename=fwh-billing-history.csv"})
        return {"periods": rows}

    @app.post("/api/billing/close")
    def api_billing_close(gateway: str | None = Query(None)):
        """Manually close the CURRENT billing period now — snapshots its itemised breakdown
        into history immediately (rather than waiting for the cycle to roll over). The
        automatic rollover later replaces that row with the final numbers, so there is no
        duplicate. Returns {ok, closed, period} or {ok:false, reason}."""
        from . import billing
        st = _ha_store()
        if st is None:
            return {"ok": False, "reason": "metrics store is disabled"}
        return billing.force_close_current(st, gateway)

    @app.post("/api/billing/import")
    def api_billing_import(req: BillingImportReq, gateway: str | None = Query(None)):
        """Backfill closed billing periods from a Modbus bridge ``/api/tariff/history`` payload
        (same physical aGate). Idempotent — re-importing replaces same-period rows. Returns
        {ok, imported, skipped}."""
        from . import billing
        st = _ha_store()
        if st is None:
            return {"ok": False, "reason": "metrics store is disabled"}
        return billing.import_modbus_periods(st, req.periods, gateway or req.gateway)

    @app.post("/api/billing/import-modbus")
    def api_billing_import_modbus(req: BillingImportModbusReq, gateway: str | None = Query(None)):
        """One-click: log in to a Modbus bridge, pull its closed periods, and import them.
        ``dry_run`` previews (fetch + count, no write). Idempotent. Returns {ok, imported,
        skipped} — or {ok:false, reason} on a bad URL / auth / network failure."""
        from . import billing
        st = _ha_store()
        if st is None:
            return {"ok": False, "reason": "metrics store is disabled"}
        url = (req.source_url or get_settings().modbus_bridge_url or "").strip()
        if not url:
            return {"ok": False, "reason": "no Modbus bridge URL — enter one or set MODBUS_BRIDGE_URL"}
        try:
            periods = billing.fetch_modbus_history(url, req.username or "admin", req.password or "admin")
        except Exception as e:  # noqa: BLE001 — surface the fetch/auth error to the UI
            return {"ok": False, "reason": f"could not fetch from {url}: {e}"}
        if req.dry_run:
            return {"ok": True, "dry_run": True, "available": len(periods),
                    "sample": periods[:3]}
        out = billing.import_modbus_periods(st, periods, gateway or req.gateway)
        out["fetched"] = len(periods)
        return out

    @app.post("/api/gateways/{gw_id}/restart")
    async def api_gateway_restart(gw_id: str):
        """Reconnect one gateway's poller (and its mock emulator) — applies any changed
        host/port/poll settings that only take effect on reconnect."""
        _guard_writes()
        st = _gw_store()
        if st is None:
            raise HTTPException(503, "metrics store is disabled; gateway roster needs it")
        row = st.gateway(gw_id)
        if row is None:
            raise HTTPException(404, f"no gateway '{gw_id}'")
        await _reconcile_gateway(row)
        return _gw_merged(row)

    def _default_scan_subnet() -> str:
        """A /24 to sweep — derived from a configured (non-mock) gateway host, else the
        library's local-subnet guess, else a common default."""
        from franklinwh_local import discover as _disc
        st = _gw_store()
        hosts = [r.get("host") for r in (st.gateways() if st else [])
                 if r.get("host") and not r.get("is_mock")]
        guess = _disc.default_gateway()
        for h in hosts + ([guess] if guess else []):
            parts = (h or "").split(".")
            if len(parts) == 4 and all(p.isdigit() for p in parts):
                return f"{parts[0]}.{parts[1]}.{parts[2]}.0/24"
        return "192.168.1.0/24"

    @app.post("/api/gateways/scan")
    async def api_gateway_scan(req: GatewayScanReq):
        """Sweep a subnet for aGates on TCP 9000 and confirm each with a real Local-API
        login (1101/1102). Returns candidates; the UI adds the confirmed ones."""
        from franklinwh_local import discover as _disc
        subnet = (req.subnet or _default_scan_subnet()).strip()
        try:
            targets = _disc.expand_targets(subnet)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(400, f"bad subnet '{subnet}': {e}")
        if len(targets) > 1024:
            raise HTTPException(400, "subnet too large (>1024 hosts) — narrow it")
        results = await asyncio.to_thread(
            _disc.scan, targets, ports=(_disc.PORT_SENDMQTT,), probe=True, timeout=1.0)
        st = _gw_store()
        existing = {r.get("host") for r in (st.gateways() if st else [])}
        cands = []
        for r in results:
            if not getattr(r, "sendmqtt_open", False):
                continue
            serial = (r.manifest or {}).get("IBG_SN") if r.manifest else None
            cands.append({
                "host": r.host,
                "confirmed": bool(getattr(r, "sendmqtt_confirmed", False)),
                "serial": serial,
                "already_added": r.host in existing,
            })
        cands.sort(key=lambda c: (not c["confirmed"], c["host"]))
        return {"subnet": subnet, "count": len(cands), "candidates": cands}

    @app.get("/api/gateways/{gw_id}/summary")
    def api_gateway_summary(gw_id: str):
        """One gateway's full summary — the poller's cached last-good copy when warm,
        else an on-demand read of that gateway's host. 404 for an unknown id."""
        gw = state.get_gateway(gw_id)
        if gw is None:
            raise HTTPException(status_code=404, detail=f"unknown gateway {gw_id!r}")
        return _gateway_summary(gw)

    @app.get("/api/site/status")
    def api_site_status():
        """Whole-site aggregation across every registered gateway, from their poller
        caches (no device I/O). Never 500s — cold caches contribute zeros / ok:false.
        ``totals`` sums the power fields over the OK gateways only."""
        gws = state.gateways() or [get_state()]
        keys = ("grid_w", "solar_w", "battery_w", "load_w", "generator_w")
        totals = {k: 0 for k in keys}
        ok_count = 0
        for gw in gws:
            summ = gw.last_summary or {}
            if not summ.get("ok"):
                continue
            ok_count += 1
            power = summ.get("power") or {}
            for k in keys:
                v = power.get(k)
                if isinstance(v, (int, float)):
                    totals[k] += v
        return {"count": len(gws), "ok_count": ok_count, "totals": totals,
                "gateways": [_roster_entry(gw) for gw in gws]}

    def _read(fn, gateway: str | None = None):
        host = _gw_host(gateway)
        try:
            return fn(get_settings(), host=host)
        except (OSError, TransportError, TimeoutError) as e:
            raise HTTPException(status_code=502, detail=str(e))

    @app.get("/api/power")
    def api_power(gateway: str | None = Query(None)):
        return _read(client.power, gateway)

    @app.get("/api/der-comms")
    def api_der_comms(gateway: str | None = Query(None)):
        return _read(client.der_comms, gateway)

    @app.get("/api/firmware")
    def api_firmware(gateway: str | None = Query(None)):
        return _read(client.firmware, gateway)

    # -- cloud-aligned facade -------------------------------------------------
    # JSON that matches the franklinwh-cloud client's response shapes 1:1, so FWHAI
    # can call the bridge first and fall back to the Cloud API. Pure translation of
    # local cmdTypes (1301 power_flow, 1409 smart_circuits) via cloud_compat.
    from . import circuits as circuits_mod, cloud_compat

    @app.get("/api/cloud/stats")
    def api_cloud_stats(gateway: str | None = Query(None)):
        """Cloud ``Stats`` shape ({current, totals, is_stale}) from local power_flow
        (+ smart_circuits for switch states) in one aGate session. 502 on device error."""
        return _read(client.cloud_stats, gateway)

    @app.get("/api/cloud/smart-circuits")
    def api_cloud_smart_circuits(gateway: str | None = Query(None)):
        """Cloud ``get_smart_circuits`` shape: {"1": {...}, "2": {...}, "3": {...}}."""
        host = _gw_host(gateway)
        try:
            payload = client.read(get_settings(), "smart_circuits", host=host)
        except (OSError, TransportError, TimeoutError) as e:
            raise HTTPException(status_code=502, detail=str(e))
        return cloud_compat.smart_circuits_map(payload)

    @app.get("/api/cloud/smart-circuits/info")
    def api_cloud_smart_circuits_info(gateway: str | None = Query(None)):
        """Raw local smart_circuits payload — mirrors cloud ``get_smart_circuits_info``."""
        host = _gw_host(gateway)
        try:
            return client.read(get_settings(), "smart_circuits", host=host)
        except (OSError, TransportError, TimeoutError) as e:
            raise HTTPException(status_code=502, detail=str(e))

    # ── generator (FEAT-GENERATOR) ───────────────────────────────────────────
    @app.get("/api/generator")
    def api_generator(gateway: str | None = Query(None)):
        """Generator config + run state (1901).

        ``installed`` is evidence-based — the gateway returns the 1901 block whether
        or not a generator exists, exactly as it does for smart circuits.
        """
        host = _gw_host(gateway)
        try:
            return client.generator(get_settings(), host=host)
        except (OSError, TransportError, TimeoutError) as e:
            raise HTTPException(status_code=502, detail=str(e))

    @app.get("/api/generator/raw")
    def api_generator_raw(gateway: str | None = Query(None)):
        """Raw 1901 payload, including fields the view-model deliberately omits."""
        host = _gw_host(gateway)
        try:
            return client.read(get_settings(), "generator", host=host)
        except (OSError, TransportError, TimeoutError) as e:
            raise HTTPException(status_code=502, detail=str(e))

    @app.post("/api/generator/mode")
    def api_generator_mode(req: GeneratorModeReq, gateway: str | None = Query(None)):
        """Set generator mode (auto/manual) — 1901 full-block RMW, read-back verified.

        409 when no generator is detected: the write is unexercised on real generator
        hardware and must not be fired blind.
        """
        _guard_writes()
        host = _gw_host(gateway)
        try:
            return client.set_generator_mode(get_settings(), req.mode, host=host)
        except client.NotInstalledError as e:
            raise HTTPException(status_code=409, detail=str(e))
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        except (OSError, TransportError, TimeoutError) as e:
            raise HTTPException(status_code=502, detail=str(e))

    @app.put("/api/circuits/{circuit}/schedule")
    def api_circuit_schedule(circuit: int, req: CircuitScheduleReq,
                             gateway: str | None = Query(None)):
        """Attempt a circuit schedule write — 1409 full-block RMW, read-back verified.

        ⚠️ The gateway **silently discards** these on the observed firmware: live-tested
        2026-09-14 (circuit 2, three payload shapes) — ``result: 0``, nothing changed,
        while an on/off write on the same command worked moments later. The response
        carries ``discarded: true`` for that case; ``ok`` is never true unless a re-read
        agrees. Retained for firmwares that may honour it, and because it is provably
        harmless — the full block is echoed and the gateway was byte-identical after.

        Up to two windows, HH:MM. Rejects an end at or before its start and any overlap
        between enabled windows — the firmware accepts both happily.
        """
        _guard_writes()
        host = _gw_host(gateway)
        today = _dt.datetime.now().strftime("%Y-%m-%d")
        try:
            return client.set_circuit_schedule(
                get_settings(), circuit,
                [w.model_dump() for w in req.windows], today, host=host)
        except ValueError as e:          # includes circuits.ScheduleError
            raise HTTPException(status_code=422, detail=str(e))
        except (OSError, TransportError, TimeoutError) as e:
            raise HTTPException(status_code=502, detail=str(e))

    @app.post("/api/raw")
    def api_raw(req: RawCmdReq, gateway: str | None = Query(None)):
        """Send one arbitrary cmdType and return the request + raw response verbatim.

        A protocol console for the gateway's owner. Reads (``opt:0``) need nothing.
        Writes need ALLOW_WRITES **and** an explicit ``confirm`` — a raw console is
        exactly where a mistyped ``opt`` becomes a reboot.
        """
        from franklinwh_local import catalog as _cat
        host = _gw_host(gateway)
        # "Not opt:0" is NOT the same as "write": 1725 READS with opt:1, and treating
        # that as a write blocked a legitimate read. Compare against the command's
        # documented read payload instead.
        read_opt = _cat.read_payload(req.cmd).get("opt")
        effective = _cat.read_payload(req.cmd) if req.data is None else req.data
        is_write = effective.get("opt") != read_opt
        if is_write:
            _guard_writes()
            if not req.confirm:
                raise HTTPException(
                    status_code=428,
                    detail=(f"cmdType {req.cmd} reads with opt={read_opt}; "
                            f"opt={req.data.get('opt')} is therefore a WRITE. "
                            f"Re-send with confirm=true. "
                            + (client.DANGEROUS_WRITES.get(req.cmd) or "")).strip())
        try:
            return client.raw_command(get_settings(), req.cmd, req.data, host=host)
        except (OSError, TransportError, TimeoutError) as e:
            # A closed connection is the gateway's way of rejecting an out-of-band
            # cmdType — report it as data, not as a bridge failure.
            raise HTTPException(status_code=502, detail=f"{type(e).__name__}: {e}")

    @app.get("/api/raw/catalog")
    def api_raw_catalog():
        """Known cmdTypes for the console's autocomplete: code, name, description."""
        from franklinwh_local import catalog
        return {
            "commands": [
                {"cmd": code, "name": i.name, "description": i.description,
                 "response_cmd": i.response,
                 # The payload a READ actually needs. 1725 answers ONLY opt:1;
                 # opt:0 draws no reply and the console just hangs.
                 "read_payload": catalog.read_payload(code),
                 "dangerous_write": client.DANGEROUS_WRITES.get(code)}
                for code, i in sorted(catalog.CATALOG.items())
            ],
            "writes": {k: v for k, v in catalog.WRITES.items()},
            "discarded": {k: v["cmd"] for k, v in catalog.DISCARDED_WRITES.items()},
        }

    @app.get("/api/firmware/all")
    def api_firmware_all(gateway: str | None = Query(None)):
        """Gateway firmware PLUS per-battery firmware and serials.

        ``/api/firmware`` returns the flat 1101 manifest and is left alone — its shape
        is already consumed elsewhere. This adds the per-device half (1833), which the
        manifest cannot express: its arrays carry one entry per aPower but nothing says
        which battery each belongs to, and it omits ibg_iot / ibg_local / pe_ver.
        """
        host = _gw_host(gateway)
        try:
            return client.firmware_all(get_settings(), host=host)
        except (OSError, TransportError, TimeoutError) as e:
            raise HTTPException(status_code=502, detail=str(e))

    # ── Home Assistant instances (multi-HA) ──────────────────────────────────
    def _ha_store():
        st = db.get_store(get_settings())
        if st is None:
            raise HTTPException(status_code=503,
                                detail="metrics store is disabled; HA instances need it")
        return st

    @app.get("/api/ha/instances")
    def api_ha_instances():
        """Configured HA instances. Tokens are never returned — only whether set."""
        return {"instances": [ha_instances.redact(r) for r in _ha_store().ha_instances()]}

    @app.post("/api/ha/instances", status_code=201)
    def api_ha_instance_create(req: HaInstanceCreate):
        _guard_writes()
        import uuid
        st = _ha_store()
        row = st.create_ha_instance(
            ha_id=uuid.uuid4().hex[:12], name=req.name, base_url=req.base_url,
            token=req.token, is_default=req.is_default, enabled=req.enabled)
        return ha_instances.redact(row)

    @app.patch("/api/ha/instances/{ha_id}")
    def api_ha_instance_update(ha_id: str, req: HaInstanceUpdate):
        _guard_writes()
        st = _ha_store()
        if st.ha_instance(ha_id) is None:
            raise HTTPException(status_code=404, detail=f"no HA instance '{ha_id}'")
        row = st.update_ha_instance(ha_id, **req.model_dump(exclude_unset=True))
        return ha_instances.redact(row)

    @app.delete("/api/ha/instances/{ha_id}")
    def api_ha_instance_delete(ha_id: str):
        _guard_writes()
        if not _ha_store().delete_ha_instance(ha_id):
            raise HTTPException(status_code=404, detail=f"no HA instance '{ha_id}'")
        return {"deleted": ha_id}

    @app.post("/api/ha/test")
    def api_ha_test(req: HaTestReq):
        """Probe a connection. Returns the outcome rather than raising."""
        token = req.token
        if not token and req.ha_id:
            stored = _ha_store().ha_instance(req.ha_id)
            token = (stored or {}).get("token")
        return ha_instances.probe(req.base_url, token)

    @app.get("/api/ha/entities")
    def api_ha_entities(instance: str | None = Query(None),
                        domain: str | None = Query(None),
                        search: str | None = Query(None),
                        topic: str | None = Query(None),
                        exposed: bool | None = Query(None),
                        limit: int = Query(200, ge=1, le=1000)):
        """Browse entities across the configured instances, with the same filters
        the Modbus Bridge's HA Entities tab offers: instance, domain, comma-OR
        search, topic preset, and exposed-only.

        The domain list and the totals (entities / exposed / instances) reflect the
        WHOLE instance set, not the filtered page, so the dropdown does not shrink as
        you filter. One unreachable instance reports its error alongside the rest.
        """
        st = _ha_store()
        out = ha_instances.entities(st, instance_id=instance, domain=domain,
                                    search=search, topic=topic, exposed=exposed,
                                    exposed_ids=st.ha_exposed_ids(), limit=limit)
        out["instances"] = len(st.ha_instances())
        return out

    @app.post("/api/ha/entities/expose")
    def api_ha_expose(req: HaExposeReq):
        """Mark one entity visible/exposed (the checkbox in the browser)."""
        _guard_writes()
        _ha_store().set_ha_exposed(req.instance_id, req.entity_id, req.exposed)
        return {"instance_id": req.instance_id, "entity_id": req.entity_id,
                "exposed": req.exposed}

    @app.get("/api/ha/notify-targets")
    def api_ha_notify_targets():
        """``notify.*`` services per instance — these are services, not entities,
        so they never appear in an entity list."""
        st = _ha_store()
        out, errors = [], {}
        for inst in st.ha_instances():
            if not inst.get("enabled"):
                continue
            try:
                for target in ha_instances.notify_targets(inst["base_url"],
                                                          inst.get("token")):
                    out.append({"instance_id": inst["id"], "instance": inst["name"],
                                "service": target})
            except Exception as e:                               # noqa: BLE001
                errors[inst["id"]] = f"{type(e).__name__}: {e}"
        return {"targets": out, "errors": errors}

    @app.get("/api/ha/notify-devices")
    def api_notify_devices():
        """Named notification targets, each independently enabled.

        ``master_enabled`` is the global switch (``ha_notify``): a device can be on
        while notifications as a whole are off, so both are reported.
        """
        st = _ha_store()
        by_id = {i["id"]: i["name"] for i in st.ha_instances()}
        return {
            "master_enabled": bool(get_settings().ha_notify),
            "devices": [{**d, "enabled": bool(d["enabled"]),
                         "instance": by_id.get(d["instance_id"], "(missing instance)"),
                         "instance_missing": d["instance_id"] not in by_id}
                        for d in st.notify_devices()],
        }

    @app.post("/api/ha/notify-devices", status_code=201)
    def api_notify_device_create(req: NotifyDeviceCreate):
        _guard_writes()
        import uuid
        st = _ha_store()
        if st.ha_instance(req.instance_id) is None:
            raise HTTPException(status_code=422,
                                detail=f"no HA instance '{req.instance_id}'")
        return st.create_notify_device(
            dev_id=uuid.uuid4().hex[:12], alias=req.alias,
            instance_id=req.instance_id, service=req.service, enabled=req.enabled)

    @app.patch("/api/ha/notify-devices/{dev_id}")
    def api_notify_device_update(dev_id: str, req: NotifyDeviceUpdate):
        """Also the per-device on/off — disabling must not require deleting, or a
        week's pause costs the configuration."""
        _guard_writes()
        st = _ha_store()
        if st.notify_device(dev_id) is None:
            raise HTTPException(status_code=404, detail=f"no device '{dev_id}'")
        return st.update_notify_device(dev_id, **req.model_dump(exclude_unset=True))

    @app.delete("/api/ha/notify-devices/{dev_id}")
    def api_notify_device_delete(dev_id: str):
        _guard_writes()
        if not _ha_store().delete_notify_device(dev_id):
            raise HTTPException(status_code=404, detail=f"no device '{dev_id}'")
        return {"deleted": dev_id}

    @app.post("/api/ha/notify-devices/test")
    def api_notify_device_test(req: NotifyTestReq):
        """Send a test notification — to a saved device, or to an unsaved
        instance+service so it can be confirmed BEFORE saving."""
        st = _ha_store()
        instance_id, service = req.instance_id, req.service
        if req.device_id:
            dev = st.notify_device(req.device_id)
            if dev is None:
                raise HTTPException(status_code=404, detail=f"no device '{req.device_id}'")
            instance_id, service = dev["instance_id"], dev["service"]
        if not instance_id or not service:
            raise HTTPException(status_code=422,
                                detail="need device_id, or instance_id + service")
        inst = st.ha_instance(instance_id)
        if inst is None:
            raise HTTPException(status_code=422, detail=f"no HA instance '{instance_id}'")
        return ha_instances.send_notification(
            inst["base_url"], inst.get("token"), service, req.title, req.message)

    @app.post("/api/ha/notify-devices/broadcast")
    def api_notify_broadcast(req: NotifyBroadcastReq):
        """Send one notification to many devices — all enabled devices, or an
        explicit device_ids list. Sending is not a device write, so (like the
        per-device test) it is not gated by allow_writes; the result IS the answer."""
        st = _ha_store()
        inst_by_id = {i["id"]: i for i in st.ha_instances()}
        targets = st.notify_devices()
        if req.device_ids is not None:
            want = set(req.device_ids)
            targets = [d for d in targets if d["id"] in want]
        else:
            targets = [d for d in targets if d["enabled"]]
        results, sent = [], 0
        for d in targets:
            inst = inst_by_id.get(d["instance_id"])
            if inst is None:
                results.append({"device_id": d["id"], "alias": d["alias"],
                                "ok": False, "error": "missing instance"})
                continue
            r = ha_instances.send_notification(
                inst["base_url"], inst.get("token"), d["service"], req.title, req.message)
            if r.get("ok"):
                sent += 1
            results.append({"device_id": d["id"], "alias": d["alias"], **r})
        return {"sent": sent, "total": len(targets), "results": results}

    # ── notification trigger engine (FEAT-NOTIFY) ─────────────────────────────
    @app.get("/api/notify/triggers")
    def api_notify_triggers():
        """The configurable auto-notification triggers + per-event delivery stats."""
        from . import notify_engine
        st = _ha_store()
        return {"config": notify_engine.config(st), "stats": (st.notify_stats() if st else [])}

    @app.put("/api/notify/triggers")
    def api_notify_triggers_put(req: NotifyTriggersBody):
        from . import notify_engine
        st = _ha_store()
        cfg = notify_engine.set_config(st, req.model_dump(exclude_none=True))
        return {"config": cfg}

    @app.get("/api/notify/log")
    def api_notify_log(limit: int = Query(100, ge=1, le=500), event: str | None = Query(None)):
        st = _ha_store()
        return {"events": (st.notify_log(limit=limit, event=event) if st else [])}

    @app.post("/api/notify/triggers/test")
    def api_notify_triggers_test():
        """Fire a test notification through the engine (delivered + logged like a real one)."""
        from . import notify_engine
        st = _ha_store()
        if st is None:
            raise HTTPException(status_code=503, detail="metrics store is off")
        sent = notify_engine.fire(st, "test", "FranklinWH — test",
                                  "This is a test notification from the trigger engine.")
        return {"ok": True, "sent": sent}

    # ── scheduler ────────────────────────────────────────────────────────────
    @app.get("/api/system-setup")
    def api_system_setup(gateway: str | None = Query(None)):
        """Per-gateway System Setup: resolved values (default → derived → override) + spec."""
        from . import system_setup
        st = _gw_store()
        return {"values": system_setup.values(st, get_settings(), gateway, _gw_host(gateway)),
                "spec": system_setup.spec()}

    @app.put("/api/system-setup")
    def api_system_setup_put(req: SystemSetupBody, gateway: str | None = Query(None)):
        """Set user overrides (null reverts a field to the derived value). No device write."""
        from . import system_setup
        st = _gw_store()
        if st is None:
            raise HTTPException(503, "metrics store is disabled")
        system_setup.update(st, gateway, req.model_dump(exclude_unset=True))
        return {"values": system_setup.values(st, get_settings(), gateway, _gw_host(gateway)),
                "spec": system_setup.spec()}

    @app.get("/api/constants")
    def api_constants():
        """User-defined automation constants + their [min,max] bounds (const.* sensors)."""
        from . import constants
        st = _gw_store()
        return {"values": constants.values(st), "spec": constants.spec()}

    @app.get("/api/constants/modes")
    def api_constants_modes(gateway: str | None = Query(None)):
        """Operating-mode options for the Default-Mode picker, DERIVED from what this
        aGate actually reports (mode_list). Falls back to the full catalogue if the
        device can't be reached, so the picker is never empty."""
        from . import constants
        catalogue = constants.spec()["default_operating_mode"]["options"]
        try:
            reserves = client.cloud_reserves(get_settings(), host=_gw_host(gateway))
            avail = {constants.WORKMODE_ALIAS.get(r.get("workMode"))
                     for r in (reserves or []) if r.get("workMode") in constants.WORKMODE_ALIAS}
            opts = [o for o in catalogue if o["value"] in avail] or catalogue
            return {"options": opts, "derived": bool(avail)}
        except Exception:                                        # noqa: BLE001
            return {"options": catalogue, "derived": False}

    @app.put("/api/constants")
    def api_constants_put(req: ConstantsBody):
        """Update automation constants (only sent fields; each clamped to its bounds)."""
        _guard_writes()
        from . import constants
        st = _gw_store()
        if st is None:
            raise HTTPException(503, "metrics store is disabled")
        try:
            vals = constants.update(st, req.model_dump(exclude_unset=True, exclude_none=True))
        except (ValueError, TypeError):
            raise HTTPException(422, "constants must be numeric")
        return {"values": vals, "spec": constants.spec()}

    @app.get("/api/schedules")
    def api_schedules():
        """Schedules plus the action catalogue — including what is NOT available
        and why, so the UI never offers a control that does nothing."""
        from . import battery_control
        _force_ok, _force_why = battery_control.available()
        _now = _dt.datetime.now()
        _scheds = _ha_store().schedules()
        for _e in _scheds:
            _lfd = _e.get("last_fired_day")
            _e["next_fire"] = scheduler.next_fire_ts(_e, _now, _lfd)
            _e["active_now"] = scheduler.active_now(_e, _now, _lfd)
        return {
            "schedules": _scheds,
            "actions": scheduler.ACTIONS,
            "unavailable": scheduler.UNAVAILABLE,
            "force_available": _force_ok,
            "force_reason": _force_why,
            "trigger_types": list(scheduler.TRIGGER_TYPES),
            "cron_available": scheduler.cron_available(),
            "sensors": (
                [{"id": i, "label": l, "group": "Gateway"}
                 for i, l in scheduler.SENSORS]
                + [{"id": i, "label": l, "group": "Weather & Solar"}
                   for i, l in scheduler.SOLAR_SENSORS]
                + [{"id": i, "label": l, "group": "Tariff & Utility"}
                   for i, l in scheduler.TARIFF_SENSORS]
                + [{"id": i, "label": l, "group": "Tariff & Utility"}
                   for i, l in scheduler.BILLING_WINDOW_SENSORS]
                + [{"id": i, "label": l, "group": "Demand / Tariff"}
                   for i, l in scheduler.DEMAND_SENSORS]
                + [{"id": i, "label": l, "group": "Energy"}
                   for i, l in scheduler.ENERGY_SENSORS]
                + [{"id": i, "label": l, "group": "Demand / Tariff"}
                   for i, l in scheduler.BONUS_SENSORS]
                + [{"id": i, "label": l, "group": "Tariff & Utility"}
                   for i, l in scheduler.EXPORT_CHARGE_SENSORS]
                + [{"id": i, "label": l, "group": "Fixed Charges"}
                   for i, l in scheduler.FIXED_SENSORS]
                + [{"id": i, "label": l, "group": "System Setup"}
                   for i, l in scheduler.SYSTEM_SENSORS]
                + [{"id": i, "label": l, "group": "Automation Constants"}
                   for i, l in scheduler.CONST_SENSORS]
                + [{"id": i, "label": l, "group": "Derived Battery"}
                   for i, l in scheduler.DERIVED_SENSORS]
                + scheduler.ha_sensor_options(_ha_store())
            ),
            "gateways": [{"id": g.id, "name": g.label or g.serial or g.id,
                          "host": g.active_host or g.configured_host}
                         for g in get_gateways()],
            "ops": list(scheduler.OPERATORS),
            "text_rhs_ops": list(scheduler.TEXT_RHS_OPERATORS),
        }

    @app.post("/api/schedules", status_code=201)
    def api_schedule_create(req: ScheduleReq):
        _guard_writes()
        import uuid
        st = _ha_store()
        spec = req.model_dump(exclude={"name", "enabled"})
        sid = uuid.uuid4().hex[:12]
        row = st.create_schedule(sid=sid, name=req.name, spec=spec, enabled=req.enabled)
        try:
            st.log_schedule_event(sid, req.name, "created",
                                  f"created {'enabled' if req.enabled else 'disabled'}")
        except Exception:  # noqa: BLE001
            pass
        return row

    @app.put("/api/schedules/{sid}")
    def api_schedule_update(sid: str, req: ScheduleReq):
        _guard_writes()
        st = _ha_store()
        prior = st.schedule(sid)
        if prior is None:
            raise HTTPException(status_code=404, detail=f"no schedule '{sid}'")
        spec = req.model_dump(exclude={"name", "enabled"})
        row = st.update_schedule(sid, name=req.name, enabled=req.enabled, spec=spec)
        try:
            if prior.get("enabled") != req.enabled:
                st.log_schedule_event(sid, req.name,
                                      "enabled" if req.enabled else "disabled", "toggled")
            else:
                st.log_schedule_event(sid, req.name, "updated", "settings changed")
        except Exception:  # noqa: BLE001
            pass
        return row

    @app.delete("/api/schedules/{sid}")
    def api_schedule_delete(sid: str):
        _guard_writes()
        st = _ha_store()
        prior = st.schedule(sid)
        if not st.delete_schedule(sid):
            raise HTTPException(status_code=404, detail=f"no schedule '{sid}'")
        try:
            st.log_schedule_event(sid, (prior or {}).get("name") or sid, "deleted", "removed")
        except Exception:  # noqa: BLE001
            pass
        return {"deleted": sid}

    @app.post("/api/schedules/{sid}/stop")
    def api_schedule_stop(sid: str):
        """Release just THIS schedule's running battery dispatch (leaves it enabled),
        vs the global topbar Release. No-op with a clear message if it owns nothing."""
        _guard_writes()
        st = _ha_store()
        entry = st.schedule(sid)
        if entry is None:
            raise HTTPException(status_code=404, detail=f"no schedule '{sid}'")
        from . import battery_control
        mine = [d for d in st.active_dispatches() if d.get("schedule_id") == sid]
        host = _modbus_host()
        if mine and host:
            out = battery_control.execute("Release", host=host)
            for d in mine:
                st.end_dispatch(d["id"], status="stopped")
            st.log_schedule_event(sid, entry["name"], "stopped",
                                  f"dispatch released by user: {out.get('result', '')}")
            return {"stopped": True, "result": out.get("result", "")}
        st.log_schedule_event(sid, entry["name"], "stopped", "no active dispatch to stop")
        return {"stopped": False, "result": "no active dispatch for this schedule"}

    @app.get("/api/schedules/presets")
    def api_schedule_presets():
        """Built-in schedule templates for the Load Preset dialog. Every action is
        one the local channel can actually do — no force-charge preset."""
        return {"presets": scheduler.PRESETS}

    @app.get("/api/schedules/export")
    def api_schedules_export(ids: str | None = Query(None), fmt: str = Query("native")):
        """Portable JSON bundle of schedules. ``ids`` = comma-separated (default all).
        ``fmt=automations`` emits the Modbus bridge's ``franklinwh-automations`` schema so
        the two bridges interchange both ways; ``native`` (default) is this bridge's own."""
        rows = _ha_store().schedules()
        if ids:
            want = {i.strip() for i in ids.split(",") if i.strip()}
            rows = [r for r in rows if r["id"] in want]
        if fmt == "automations":
            return {"type": scheduler.IMPORT_TYPE_AUTOMATIONS, "version": 1,
                    "entries": [scheduler.to_automations(r) for r in rows]}
        return {"type": scheduler.EXPORT_TYPE, "version": scheduler.EXPORT_VERSION,
                "entries": [scheduler.portable(r) for r in rows]}

    @app.post("/api/schedules/import")
    def api_schedules_import(req: ScheduleImportReq,
                             dry_run: bool = Query(True)):
        """Validate a bundle; with ``dry_run=false`` create the valid entries
        DISABLED for review. An unknown gateway falls back to the default, and a
        missing notify device is flagged rather than blocking the import."""
        _known = {scheduler.EXPORT_TYPE, scheduler.IMPORT_TYPE_AUTOMATIONS}
        if req.type and req.type not in _known:
            raise HTTPException(
                status_code=400,
                detail=(f"unexpected bundle type '{req.type}' — this importer reads "
                        f"'{scheduler.EXPORT_TYPE}' (this bridge) and "
                        f"'{scheduler.IMPORT_TYPE_AUTOMATIONS}' (the Modbus bridge)."))
        # Normalise a foreign bundle (Modbus 'franklinwh-automations') to our schema; our
        # own bundle passes through unchanged.
        entries = scheduler.import_entries(req.type, req.entries)
        st = _ha_store()
        gw_ids = {g.id for g in get_gateways()}
        dev_ids = {d["id"] for d in st.notify_devices()}
        reports = [scheduler.validate_import(e, gateway_ids=gw_ids, device_ids=dev_ids)
                   for e in entries]
        if dry_run:
            return {"entries": reports, "count": len(reports),
                    "importable": sum(1 for r in reports if r["ok"]),
                    "mapped_from": req.type if req.type == scheduler.IMPORT_TYPE_AUTOMATIONS else None}
        _guard_writes()
        import uuid
        created, skipped = [], []
        for e, rep in zip(entries, reports):
            if not rep["ok"]:
                skipped.append({"name": rep["name"], "errors": rep["errors"]})
                continue
            spec = scheduler.portable(e)
            if spec.get("gateway_id") and spec["gateway_id"] not in gw_ids:
                spec["gateway_id"] = ""     # unknown gateway → default
            name = spec.pop("name", "imported")
            spec.pop("enabled", None)
            row = st.create_schedule(sid=uuid.uuid4().hex[:12], name=name,
                                     spec=spec, enabled=False)  # disabled for review
            created.append(row["id"])
        return {"created": created, "skipped": skipped}

    @app.get("/api/schedules/log")
    def api_schedule_log(limit: int = Query(100, ge=1, le=500),
                         schedule_id: str | None = Query(None),
                         status: str | None = Query(None)):
        """Recent schedule fires, newest first — the history view.

        Filter by ``schedule_id`` (one entry's runs) or ``status`` (fired/error).
        A schedule that fired and did nothing still appears, with the reason.
        """
        return {"events": _ha_store().schedule_log(
            limit=limit, schedule_id=schedule_id, status=status)}

    @app.get("/api/schedules/timeline")
    def api_schedule_timeline(gateway: str | None = Query(None)):
        """Today's timeline: each enabled schedule's planned window, plus the real
        work-mode band, the SoC % line, and fire markers from the activity log — all
        in minutes-from-midnight. (No VPP-override band: the local channel has no
        force provider, so only the actual work mode is shown.)"""
        import datetime as _d
        now = _d.datetime.now()
        base = scheduler.timeline_segments(_ha_store().schedules(), now)
        midnight = int(now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
        now_ts = int(now.timestamp())
        def to_min(ts: float) -> float:
            return max(0.0, min(1440.0, (ts - midnight) / 60.0))
        soc: list = []; modes: list = []; fires: list = []
        store = db.get_store(get_settings())
        if store is not None:
            key = _metrics_gw_key(gateway)
            for row in store.query(midnight, now_ts, 300, gateway=key):
                if row.get("soc") is not None:
                    soc.append({"min": round(to_min(row["ts"]), 1), "soc": row["soc"]})
            for seg in store.mode_segments(midnight, now_ts, gateway=key):
                if seg.get("mode"):
                    modes.append({"start_min": round(to_min(seg["start"]), 1),
                                  "end_min": round(to_min(seg["end"]), 1),
                                  "mode": seg["mode"]})
            for ev in _ha_store().schedule_log(limit=300):
                if ev["ts"] >= midnight and ev["status"] in ("fired", "exit", "gated", "error"):
                    fires.append({"min": round(to_min(ev["ts"]), 1),
                                  "name": ev["name"], "status": ev["status"]})
        base.update({"soc": soc, "modes": modes, "fires": fires})
        return base

    @app.post("/api/schedules/{sid}/test")
    def api_schedule_test(sid: str, gateway: str | None = Query(None)):
        """Evaluate the conditions against live values WITHOUT firing anything —
        the 'Test verification' the user asked for."""
        st = _ha_store()
        entry = st.schedule(sid)
        if entry is None:
            raise HTTPException(status_code=404, detail=f"no schedule '{sid}'")
        gw = get_state()
        snap = scheduler.snapshot_from_state(getattr(gw, "last_state", {}) or {})
        snap.update(scheduler.ha_snapshot(st))
        snap.update(scheduler.solar_snapshot(get_settings()))
        snap.update(scheduler.nem_snapshot(get_settings()))
        snap.update(scheduler.ha_price_snapshot(get_settings(), st))
        snap.update(scheduler.tariff_snapshot(st, gateway))
        scheduler.apply_dynamic_pricing(snap, get_settings(), st, gateway)   # per-tariff wholesale override
        snap.update(scheduler.billing_snapshot(st, gateway))
        snap.update(__import__("franklinwh_direct_connect_bridge.billing", fromlist=["billing"]).billing_read(st, gateway))
        snap.update(__import__("franklinwh_direct_connect_bridge.billing", fromlist=["billing"]).fixed_snapshot(st, gateway))
        try:
            snap.update(__import__("franklinwh_direct_connect_bridge.system_setup", fromlist=["system_setup"]).snapshot(st, get_settings(), gateway, _gw_host(gateway)))
        except Exception:  # noqa: BLE001
            pass
        snap.update(scheduler.const_snapshot(st))
        snap.update(scheduler.ratings_snapshot(_gw_host(gateway)))
        snap.update(scheduler.derived_snapshot(snap))
        import datetime as _d
        now = _d.datetime.now()
        would, reason = scheduler.due(entry, now, snap, entry.get("last_fired_day"))
        rows = []
        for row in entry.get("conditions") or []:
            rows.append({**row, "actual": snap.get(row.get("sensor")),
                         "passes": scheduler.evaluate([row], snap)})
        return {"would_fire": would, "reason": reason,
                "window": scheduler.window_state(entry, now),
                "rows": rows, "snapshot": snap}

    @app.post("/api/schedules/evaluate")
    def api_schedule_evaluate(req: ConditionEvalReq, gateway: str | None = Query(None)):
        """Evaluate an UNSAVED condition tree against live values — the editor's
        Test Verification. Returns per-leaf pass/fail (`result` + `live_value`) so
        the UI can outline each row green/red/amber, plus the overall result."""
        st = _ha_store()
        gw = (get_gateway(gateway) or get_state()) if gateway else get_state()
        snap = scheduler.snapshot_from_state(getattr(gw, "last_state", {}) or {})
        snap.update(scheduler.ha_snapshot(st))
        snap.update(scheduler.solar_snapshot(get_settings()))
        snap.update(scheduler.nem_snapshot(get_settings()))
        snap.update(scheduler.ha_price_snapshot(get_settings(), st))
        snap.update(scheduler.tariff_snapshot(st, gateway))
        scheduler.apply_dynamic_pricing(snap, get_settings(), st, gateway)   # per-tariff wholesale override
        snap.update(scheduler.billing_snapshot(st, gateway))
        snap.update(__import__("franklinwh_direct_connect_bridge.billing", fromlist=["billing"]).billing_read(st, gateway))
        snap.update(__import__("franklinwh_direct_connect_bridge.billing", fromlist=["billing"]).fixed_snapshot(st, gateway))
        try:
            snap.update(__import__("franklinwh_direct_connect_bridge.system_setup", fromlist=["system_setup"]).snapshot(st, get_settings(), gateway, _gw_host(gateway)))
        except Exception:  # noqa: BLE001
            pass
        snap.update(scheduler.const_snapshot(st))
        snap.update(scheduler.ratings_snapshot(_gw_host(gateway)))
        snap.update(scheduler.derived_snapshot(snap))
        trace: list[dict] = []
        result = scheduler.evaluate(req.conditions, snap, req.match, trace)
        return {"result": result, "per_condition": trace}

    @app.post("/api/schedules/{sid}/run")
    def api_schedule_run(sid: str, gateway: str | None = Query(None)):
        """Run a schedule's actions NOW, ignoring its window. Still honours the
        write gate — this performs real actions."""
        _guard_writes()
        st = _ha_store()
        entry = st.schedule(sid)
        if entry is None:
            raise HTTPException(status_code=404, detail=f"no schedule '{sid}'")
        # A schedule carries its own gateway; the query param only overrides for a
        # manual run. Falling back to the default when neither is set.
        target_gw = gateway or entry.get("gateway_id") or None
        gw = (get_gateway(target_gw) or get_state()) if target_gw else get_state()
        snap = scheduler.snapshot_from_state(getattr(gw, "last_state", {}) or {})
        snap.update(scheduler.ha_snapshot(st))
        host = _gw_host(target_gw)
        results = []
        if (entry.get("action") or {}).get("kind"):
            _dur = int(entry.get("duration_min") or 0)
            results.append(scheduler.run_action(
                entry["action"], settings=get_settings(), client=client,
                store=st, snapshot=snap, host=host, window_min=_dur,
                gateway_id=target_gw, schedule_id=entry["id"],
                schedule_name=entry["name"],
                window_end_ts=(time.time() + _dur * 60) if _dur else None))
        # Manual run simulates an entry fire: fire/both actions, honouring guards
        # (never exit-only actions, and never a guard that does not currently hold).
        results += scheduler._fire_ha_phase(entry, "fire", settings=get_settings(),
                                            client=client, store=st, snapshot=snap, host=host)
        st.log_schedule_event(sid, entry["name"], "manual",
                              "; ".join(results) or "nothing to do")
        return {"results": results}

    # ── Battery Control (Force charge/discharge/standby via DIRECT Modbus WSet) ──
    # The local bridge speaks Modbus straight to the aGate (the proven
    # franklinwh-modbus library) — independent of the modbus-bridge service. Until
    # that path is installed + configured we report it plainly; the widget stays a
    # read-only control rather than a button that lies.
    _batt_cmd = {"power_w": 0, "power_pct": 100, "power_mode": "pct",
                 "duration_s": 0, "target_soc": 0, "active": "Not Active", "result": ""}
    _avail_cache = {"ts": 0.0, "val": None}

    def _bc_is_enabled() -> bool:
        try:
            from . import battery_control
            return bool(battery_control.is_enabled())
        except Exception:  # noqa: BLE001
            return False

    def _modbus_host() -> str | None:
        # The aGate's Modbus interface is on the SAME host as its Direct-Connect
        # interface — default to the gateway host (port 502 added by battery_control),
        # overridable with FWH_MODBUS_HOST.
        try:
            return os.environ.get("FWH_MODBUS_HOST") or _gw_host(None)
        except Exception:  # noqa: BLE001
            return os.environ.get("FWH_MODBUS_HOST")

    def _battery_force_status() -> dict:
        from . import battery_control
        host = _modbus_host()
        if not host:
            return {"available": False, "reason": "no gateway host to reach over Modbus"}
        return battery_control.status(host)

    @app.get("/api/battery/command")
    def api_battery_command_state():
        from . import battery_control
        cur = battery_control.current()          # in-memory, no Modbus — cheap to poll
        _batt_cmd["active"] = cur.get("active", "Not Active")
        # The availability probe DOES hit Modbus, so cache it (~30s) for polling.
        now = time.time()
        if _avail_cache["val"] is None or now - _avail_cache["ts"] > 30:
            _avail_cache.update({"ts": now, "val": _battery_force_status()})
        st = _avail_cache["val"] or {}
        return {**_batt_cmd, "remaining_s": cur.get("remaining_s"),
                "active_target_soc": cur.get("target_soc"),
                "available": st.get("available", False), "reason": st.get("reason", ""),
                "max_charge_w": st.get("max_charge_w", 5000),
                "max_discharge_w": st.get("max_discharge_w", 5000)}

    @app.post("/api/battery/command")
    def api_battery_command(req: BatteryCmdReq, dry: bool = Query(False)):
        """Store a control value, or (on the `battery_command` slug) execute it.
        Executing actually moves the battery, so it is gated on allow_writes AND a
        reachable, configured Modbus path — otherwise it refuses with the reason."""
        slug, value = req.slug, req.value
        # Parameter slugs just stage the value for the next command.
        if slug == "battery_command_power":
            _batt_cmd["power_w"] = int(float(value or 0)); _batt_cmd["power_mode"] = "w"
            return {"ok": True, "result": "power set"}
        if slug == "battery_command_power_pct":
            _batt_cmd["power_pct"] = int(float(value or 0)); _batt_cmd["power_mode"] = "pct"
            return {"ok": True, "result": "power% set"}
        if slug == "battery_command_duration":
            _batt_cmd["duration_s"] = int(float(value or 0)); return {"ok": True, "result": "duration set"}
        if slug == "battery_command_target_soc":
            _batt_cmd["target_soc"] = int(float(value or 0)); return {"ok": True, "result": "target set"}
        if slug != "battery_command":
            raise HTTPException(status_code=422, detail=f"unknown slug '{slug}'")

        # Executing a Force/Release command — this MOVES the battery.
        _guard_writes()
        from . import battery_control
        host = _modbus_host()
        if not host:
            return {"ok": False, "result": "no gateway host to reach over Modbus",
                    "active": _batt_cmd["active"]}
        # Optional dry-run (?dry=1) computes the write without touching the battery.
        def _batt_soc():
            try:
                return (getattr(get_state(), "last_state", {}) or {}).get("soc")
            except Exception:  # noqa: BLE001
                return None
        def _batt_log(status, detail):
            try:
                st = _ha_store()
                st.log_schedule_event("_batt", "Battery dispatch", status, detail)
                # A clean end closes the persisted row so a later boot reconcile does
                # not treat this widget dispatch as interrupted.
                if status == "dispatch-end" and hasattr(st, "end_active_dispatches"):
                    st.end_active_dispatches(host=host, status="ended")
            except Exception:  # noqa: BLE001
                pass
        out = battery_control.execute(
            value, host=host, power_w=_batt_cmd["power_w"], power_pct=_batt_cmd["power_pct"],
            power_mode=_batt_cmd["power_mode"], duration_s=_batt_cmd["duration_s"],
            target_soc=_batt_cmd["target_soc"], soc_getter=_batt_soc, on_event=_batt_log,
            dry_run=dry)
        # Persist a widget-initiated force so it, too, is covered by the boot reconcile
        # policy (an interrupted one no longer falls to the generic orphan alert).
        _force_dirn = {"Force Charge": "charge", "Force Discharge": "discharge",
                       "Force Standby": "standby"}.get(value)
        try:
            store = _ha_store()
            if out.get("ok") and not dry and _force_dirn and hasattr(store, "record_dispatch"):
                mode = _batt_cmd["power_mode"]
                mag = int(_batt_cmd["power_w"] if mode == "w" else _batt_cmd["power_pct"])
                signed = (abs(mag) if _force_dirn == "charge"
                          else -abs(mag) if _force_dirn == "discharge" else 0)
                dur = int(_batt_cmd["duration_s"] or 0)
                store.record_dispatch(
                    schedule_id="_widget", name="Battery Control (widget)", gateway_id=None,
                    host=host, direction=_force_dirn, watts=signed, power_mode=mode,
                    target_soc=int(_batt_cmd["target_soc"] or 0), window_start_ts=time.time(),
                    window_end_ts=(time.time() + dur) if dur else None)
            elif out.get("ok") and not dry and value in ("Release", "Not Active") \
                    and hasattr(store, "end_active_dispatches"):
                store.end_active_dispatches(host=host, status="ended")
        except Exception:  # noqa: BLE001
            pass
        if out.get("active"):
            _batt_cmd["active"] = out["active"]
        _batt_cmd["result"] = out.get("result", "")
        return out

    @app.get("/api/ha/published")
    def api_ha_published():
        """What THIS bridge publishes to HA, so the two directions are not confused."""
        from .publish import entities as pub
        s = get_settings()
        return {
            "prefix": s.mqtt_prefix,
            "discovery_prefix": s.ha_discovery_prefix,
            "mqtt_enabled": s.mqtt_enabled,
            "entities": [
                {"key": e["key"], "name": e["name"], "unit": e.get("unit"),
                 "device_class": e.get("device_class"), "writable": False}
                for e in pub.ENTITIES
            ],
        }

    @app.get("/api/device/model")
    def api_device_model(gateway: str | None = Query(None)):
        """Gateway model/SKU/region from ``SyHdVersion`` in the login manifest.

        Unknown ids report ``known: false`` with the raw value rather than a guess.
        """
        host = _gw_host(gateway)
        try:
            return client.device_model(get_settings(), host=host)
        except (OSError, TransportError, TimeoutError) as e:
            raise HTTPException(status_code=502, detail=str(e))

    # Generator config writes — hardware-verified 2026-09-14 (1901 full-block RMW
    # with read-back). Verified on a site with NO generator fitted: the settings
    # persist, which is not the same as proving a generator acts on them.
    @app.put("/api/generator/enable")
    def api_generator_enable(req: GenEnableReq, gateway: str | None = Query(None)):
        """Turn the generator feature on/off (``genEn``).

        The official mobile app lets you enable this on a gateway with no module
        physically wired up, and the local protocol behaves the same way — so this
        succeeds regardless of hardware. Enabling a feature with nothing attached
        does nothing; the caller is expected to have warned the user.
        """
        _guard_writes()
        host = _gw_host(gateway)
        try:
            return client.set_generator_enabled(get_settings(), req.enabled, host=host)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        except (OSError, TransportError, TimeoutError) as e:
            raise HTTPException(status_code=502, detail=str(e))

    @app.put("/api/generator/window/{window}")
    def api_generator_window(window: int, req: GenWindowReq,
                             gateway: str | None = Query(None)):
        """Set one of the three generator operating windows."""
        _guard_writes()
        host = _gw_host(gateway)
        try:
            return client.set_generator_window(get_settings(), window, req.enabled,
                                               req.start, req.end, host=host)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        except (OSError, TransportError, TimeoutError) as e:
            raise HTTPException(status_code=502, detail=str(e))

    @app.put("/api/generator/exercise")
    def api_generator_exercise(req: GenExerciseReq, gateway: str | None = Query(None)):
        """Set the generator maintenance/exercise run."""
        _guard_writes()
        host = _gw_host(gateway)
        changes = {k: v for k, v in req.model_dump().items() if v is not None}
        try:
            return client.set_generator_exercise(get_settings(), host=host, **changes)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        except (OSError, TransportError, TimeoutError) as e:
            raise HTTPException(status_code=502, detail=str(e))

    @app.put("/api/generator/soc")
    def api_generator_soc(req: GenSocReq, gateway: str | None = Query(None)):
        """Set generator auto start/stop SoC thresholds."""
        _guard_writes()
        host = _gw_host(gateway)
        try:
            return client.set_generator_soc(get_settings(), req.start_below,
                                            req.stop_above, host=host)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        except (OSError, TransportError, TimeoutError) as e:
            raise HTTPException(status_code=502, detail=str(e))

    @app.get("/api/solar")
    def api_solar(gateway: str | None = Query(None)):
        """All things solar: PV inputs, remote solar/aPbox, relays, export limit.

        Groups fields the generic Live Points view cannot, because the firmware names
        them inconsistently (``installPV1port`` vs ``PV1RatedPower``, ``solarRelayStat``
        vs ``loadRelay1Stat``, and so on).
        """
        host = _gw_host(gateway)
        try:
            return client.solar(get_settings(), host=host)
        except (OSError, TransportError, TimeoutError) as e:
            raise HTTPException(status_code=502, detail=str(e))

    @app.get("/api/solar/raw")
    def api_solar_raw(gateway: str | None = Query(None)):
        """Raw 1903 payload."""
        host = _gw_host(gateway)
        try:
            return client.read(get_settings(), "solar_pv", host=host)
        except (OSError, TransportError, TimeoutError) as e:
            raise HTTPException(status_code=502, detail=str(e))

    @app.get("/api/circuits/raw")
    def api_circuits_raw(gateway: str | None = Query(None)):
        """Raw 1409 payload — the Smart Circuits counterpart to /api/generator/raw."""
        host = _gw_host(gateway)
        try:
            return client.read(get_settings(), "smart_circuits", host=host)
        except (OSError, TransportError, TimeoutError) as e:
            raise HTTPException(status_code=502, detail=str(e))

    @app.get("/api/circuits/meter")
    def api_circuits_meter(gateway: str | None = Query(None)):
        """Raw 1411 metering for the Monitoring sub-view — one read, no config."""
        host = _gw_host(gateway)
        try:
            return client.read(get_settings(), "smart_circuit_meter", host=host)
        except (OSError, TransportError, TimeoutError) as e:
            raise HTTPException(status_code=502, detail=str(e))

    # ── native smart circuits (FEAT-SMART-CIRCUITS phase 1) ──────────────────
    # Distinct from the /api/cloud/smart-circuits parity endpoints above: those
    # mirror the cloud shape exactly (always three keys, warts and all). These add
    # metering and presence detection, which the cloud surface has no room for.
    @app.get("/api/circuits")
    def api_circuits(gateway: str | None = Query(None)):
        """Smart circuits: config (1409) + metering (1411) + presence detection.

        Always returns all three circuits. ``present`` is True/False/None(unknown) with
        the evidence behind it — a circuit is never silently dropped, because "region
        has fewer circuits" and "no enclosure installed" look identical in the payload.
        """
        host = _gw_host(gateway)
        try:
            return client.circuits(get_settings(), host=host,
                                   override=get_settings().smart_circuit_count)
        except (OSError, TransportError, TimeoutError) as e:
            raise HTTPException(status_code=502, detail=str(e))

    @app.post("/api/circuits/{circuit}/power")
    def api_circuit_power(circuit: int, req: CircuitPowerReq,
                          gateway: str | None = Query(None)):
        """Turn one circuit on/off — 1409 full-block RMW with read-back verification.

        Same proven write as /api/cloud/smart-circuit/state (live-verified 2026-08-08).
        NB: this flips the config flag; power only flows where a load is wired.
        """
        _guard_writes()
        host = _gw_host(gateway)
        try:
            return client.set_smart_circuit(get_settings(), circuit, req.on, host=host)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        except (OSError, TransportError, TimeoutError) as e:
            raise HTTPException(status_code=502, detail=str(e))

    def _cloud_read(name, translate, gateway: str | None = None):
        """Read one local cmdType and run it through a cloud_compat translation fn.
        502 (clear detail) on device error — same contract as the rest of the facade."""
        host = _gw_host(gateway)
        try:
            payload = client.read(get_settings(), name, host=host)
        except (OSError, TransportError, TimeoutError) as e:
            raise HTTPException(status_code=502, detail=str(e))
        return translate(payload)

    @app.get("/api/cloud/reserves")
    def api_cloud_reserves(gateway: str | None = Query(None)):
        """Cloud ``get_all_mode_soc`` shape: list of per-mode reserve dicts
        (workMode/name/soc/minSoc/maxSoc/editSocFlag/active) from local mode_list +
        mode_soc in one aGate session. 502 on device error."""
        return _read(client.cloud_reserves, gateway)

    @app.get("/api/cloud/tou")
    def api_cloud_tou(gateway: str | None = Query(None)):
        """Cloud ``get_gateway_tou_list`` envelope ({code, message, result}) from local
        mode_list (1726, → result.currendId + result.list) enriched with tou_schedule
        (1408) in one aGate session. 502 on device error."""
        return _read(client.cloud_tou, gateway)

    @app.get("/api/cloud/mode")
    def api_cloud_mode(requestedMode: int | None = Query(None),
                       gateway: str | None = Query(None)):
        """Cloud ``get_mode`` flat dict from local power_flow + mode_list (+ mode_soc,
        tou_schedule) in one aGate session. Active mode by default; ``?requestedMode=``
        (cloud workMode 1/2/3) queries a specific mode. 502 on device error."""
        host = _gw_host(gateway)
        try:
            return client.cloud_mode(get_settings(), requestedMode, host=host)
        except (OSError, TransportError, TimeoutError) as e:
            raise HTTPException(status_code=502, detail=str(e))

    @app.get("/api/cloud/runtime")
    def api_cloud_runtime(gateway: str | None = Query(None)):
        """Cloud ``get_runtime_data`` shape from local ibg_run_status (1708)."""
        return _cloud_read("ibg_run_status", cloud_compat.runtime_from_ibg_run_status,
                           gateway)

    @app.get("/api/cloud/power-info")
    def api_cloud_power_info(gateway: str | None = Query(None)):
        """Cloud ``get_power_info`` (raw 211) shape from local relay_status (1710)."""
        return _cloud_read("relay_status", cloud_compat.power_info_from_relay_status,
                           gateway)

    @app.get("/api/cloud/device-info")
    def api_cloud_device_info(gateway: str | None = Query(None)):
        """Cloud ``get_device_info`` passthrough from local device_info (1116)."""
        return _cloud_read("device_info", cloud_compat.device_info_passthrough, gateway)

    @app.get("/api/cloud/network")
    def api_cloud_network(gateway: str | None = Query(None)):
        """Cloud ``get_network_info`` shape (currentNetType/wifi/eth0/eth1/operator/
        awsStatus) from local network_interfaces (1118)."""
        return _cloud_read("network_interfaces", cloud_compat.network_from_interfaces,
                           gateway)

    def _redact_cloud_config(cc):
        """Keep the AWS-IoT endpoint/region; never render a secret. A credential field is shown
        as ``***set***`` when present, so the diagnostic says "configured" without leaking it."""
        if not isinstance(cc, dict):
            return None
        secret = ("pw", "pass", "secret", "key", "cert", "token", "cred", "psk", "sign")
        out = {}
        for k, v in cc.items():
            if any(t in str(k).lower() for t in secret):
                out[k] = "***set***" if v not in (None, "", 0) else None
            else:
                out[k] = v
        return out

    def _bridge_ip_toward(host: str) -> str | None:
        """The bridge's own LAN IP on the path to the aGate (UDP connect → getsockname; no
        packet is actually sent). None if it can't be resolved."""
        import socket
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                s.connect((host.split(":")[0], 9000))
                return s.getsockname()[0]
            finally:
                s.close()
        except Exception:  # noqa: BLE001
            return None

    def _active_link(conn) -> str | None:
        """Which physical link is carrying traffic, from the reliable per-link flags (1113)."""
        if not isinstance(conn, dict):
            return None
        if conn.get("wifiConnectRouterStatus") == 1:
            return "wifi"
        if conn.get("EthConnectRouterStatus") == 1:
            return "eth"
        if conn.get("4GConnectBSStatus") == 1:
            return "4g"
        return None

    @app.get("/api/network")
    def api_network(request: Request, gateway: str | None = Query(None)):
        """Consolidated on-LAN network diagnostics for the selected aGate — the local answer to
        the Cloud CLI's network view, plus reachability the cloud can't see. In one session:
        reachability (:9000/:502 + latency), the router→internet→cloud chain (1113), interfaces
        + signal (1118), switches (1119), AWS-IoT endpoint (1121, redacted). Plus a ``topology``
        block (nodes + edges + ports) for the Network diagram, and the bridge's uptime."""
        s = get_settings()
        host = _gw_host(gateway)
        gw = (get_gateway(gateway) if gateway else None) or get_state()
        nb = client.network_bundle(s, host=host)
        raw_if = nb.pop("interfaces_raw", None)
        nb["interfaces"] = cloud_compat.network_from_interfaces(raw_if) if isinstance(raw_if, dict) else None
        nb["cloud"] = _redact_cloud_config(nb.get("cloud"))
        reach = nb.get("reachability") or {}
        aws_connected = bool((nb.get("interfaces") or {}).get("awsStatus") == 1)
        cloud = nb.get("cloud") or {}
        host_ip = (host or "").split(":")[0]
        try:
            ha_rows = [ha_instances.redact(r) for r in _ha_store().ha_instances()]
        except Exception:  # noqa: BLE001 — HA roster is optional; never fail the diagram
            ha_rows = []
        try:
            from .publish import entities as _ent
            _grp = _ent.enabled_from_store(_ha_store())
            _cfgs, _, _ = _ent.discovery_configs("n", _ent.device_info("n", "s"),
                                                 "franklinwh", "homeassistant", _grp)
            ha_exposed = len(_cfgs)
        except Exception:  # noqa: BLE001 — count is a nicety; never fail the diagram
            ha_exposed = None
        # Prefer the ACTUAL count the running publisher pushed for THIS gateway (the synthetic
        # discovery_configs above uses a placeholder device, so it undercounts per-aPower/2-device
        # setups — that was the wrong "21 entities").
        _pub_n = getattr(gw, "published_entities", None)
        if _pub_n is not None:
            ha_exposed = _pub_n
        nb["topology"] = {
            # aGate ← LAN → Bridge ← browser/MQTT ; aGate → AWS IoT ; account → FleetView cloud
            "agate": {"ip": host_ip, "link": _active_link(nb.get("connectivity")),
                      "ports": {"local_api_9000": bool(reach.get("sendmqtt_9000")),
                                "modbus_502": bool(reach.get("modbus_502"))},
                      "latency_ms": reach.get("latency_ms")},
            "bridge": {"ip": _bridge_ip_toward(host_ip), "http_port": 8101,
                       "uptime_s": round(time.time() - _STARTED_AT, 1),
                       "mqtt_connected": bool(getattr(gw, "mqtt_connected", False))},
            "browser": {"ip": request.client.host if request.client else None},
            "mqtt": {"host": s.mqtt_host, "port": s.mqtt_port,
                     "enabled": bool(s.mqtt_enabled),
                     "connected": bool(getattr(gw, "mqtt_connected", False))},
            "iot": {"endpoint": cloud.get("serverAddr"), "port": cloud.get("serverPort"),
                    "connected": aws_connected},   # aGate firmware → FranklinWH cloud (AWS IoT)
            "cloud_api": {"configured": bool(s.fwh_cloud_email),
                          "cf_pop": _latest_cf_pop()},   # FleetView/Cloud API CloudFront edge PoP
            # Home Assistant sees the aGate two ways: MQTT discovery (broker → HA) and a direct
            # REST link (bridge → HA) for actionable notifications + service calls.
            "home_assistant": {
                "configured": bool(ha_rows),
                "count": len(ha_rows),
                "via_mqtt": bool(s.mqtt_enabled),
                "published_entities": ha_exposed,   # entities the bridge PUBLISHES to HA via MQTT discovery (NOT the exposed/read count)
                "instances": [{"name": r.get("name"),
                               "host": (urlparse(r.get("base_url") or "").netloc or None),
                               "enabled": bool(r.get("enabled")),
                               "has_token": bool(r.get("has_token"))}
                              for r in ha_rows if r.get("enabled")],
            },
        }
        return nb

    def _latest_cf_pop():
        """The most-recent CloudFront PoP the bridge's cloud calls hit, or None."""
        try:
            from . import cloud_pop
            return cloud_pop.summary(_ha_store(), window_days=30).get("current_pop")
        except Exception:  # noqa: BLE001
            return None

    @app.get("/api/cloud/pop")
    def api_cloud_pop(window_days: int = Query(30, ge=1, le=90)):
        """CloudFront PoP edge drill-down for the FleetView/Cloud API path — current PoP, PoP
        distribution, edge transitions, cache-hit rate — aggregated from the background cloud
        poll. ``samples:0`` until the poller (needs cloud creds) has run at least once."""
        from . import cloud_pop
        s = get_settings()
        out = cloud_pop.summary(_ha_store(), window_days=window_days)
        out["cloud_creds"] = bool(s.fwh_cloud_email and s.fwh_cloud_password)
        return out

    @app.get("/api/network/ping")
    def api_network_ping(gateway: str | None = Query(None), count: int = Query(5, ge=1, le=20)):
        """Latency test: N sendMqtt round-trips to the aGate in one session. Returns per-sample
        ms + min/avg/max + loss%. The on-LAN equivalent of a ping to the Direct-Connect API."""
        s = get_settings()
        host = _gw_host(gateway)
        samples: list = []
        try:
            with client._client(s, host) as c:
                c.login()
                for _ in range(count):
                    try:
                        t0 = time.time()
                        c.power_flow()
                        samples.append(round((time.time() - t0) * 1000, 1))
                    except (OSError, TransportError, TimeoutError):
                        samples.append(None)
        except (OSError, TransportError, TimeoutError):
            samples = [None] * count
        ok = [x for x in samples if x is not None]
        return {"host": host, "count": count, "samples": samples,
                "min": min(ok) if ok else None,
                "avg": round(sum(ok) / len(ok), 1) if ok else None,
                "max": max(ok) if ok else None,
                "loss_pct": round(100 * (count - len(ok)) / count, 1) if count else 0}

    @app.get("/api/grid")
    def api_grid(gateway: str | None = Query(None)):
        """Grid & Inverter profile (read-only): grid connection + import/export power-plane limits
        from install_profile (1701), and the inverter's real max charge/discharge kW from Modbus
        SunSpec 702 (1701's fhpRatePower reads 0 on this firmware, so it is NOT the source)."""
        from . import battery_control
        s = get_settings()
        host = _gw_host(gateway)
        try:
            prof = client.read(s, "install_profile", host=host) or {}
        except (OSError, TransportError, TimeoutError, ValueError):
            prof = {}
        p = prof.get("result") if isinstance(prof.get("result"), dict) else prof
        g = lambda k: (p.get(k) if isinstance(p, dict) and k in p else prof.get(k))  # noqa: E731
        # 1701 ratedGridVolt/ratedGridHz are region ENUM CODES (0/1), not literal V/Hz — the real
        # nominal + live values come from ibg_run_status (1708).
        try:
            run = client.read(s, "ibg_run_status", host=host) or {}
        except (OSError, TransportError, TimeoutError, ValueError):
            run = {}
        rp = run.get("result") if isinstance(run.get("result"), dict) else run
        rg = lambda k: (rp.get(k) if isinstance(rp, dict) and k in rp else run.get(k))  # noqa: E731
        _num = lambda v: (float(v) if isinstance(v, (int, float)) else None)  # noqa: E731
        line_v = _num(rg("gridLineVol"))
        chg_w, dis_w = (None, None)
        try:
            chg_w, dis_w = battery_control.cached_ratings((host or "").split(":")[0])
        except Exception:  # noqa: BLE001
            pass
        return {
            "grid_connection": {
                "three_phase": bool(g("isThreePhaseInstall")),
                "phase_con": g("gridPhaseConSet"), "phase_seq": g("gridPhaseSeqSet"),
                "service_amps": g("airSwitchCur"),
                "electric_supply_raw": g("electricSupply"),
                # Real freq/voltage from 1708 (not the 1701 enum codes):
                "nominal_freq_hz": _num(rg("dspSettingFreq")),   # configured nominal, e.g. 50
                "live_freq_hz": _num(rg("gridFreq")),            # live grid frequency
                "grid_voltage_v": (round(line_v / 10, 1) if line_v else None),  # line V (÷10)
                "leg_voltage_v": _num(rg("gridVol1")),           # per-leg (split-phase)
                "rated_hz_code": g("ratedGridHz"),               # 1701 enum, NOT a Hz value
            },
            "grid_limits": {
                "export_enable": bool(g("gridExportEnable")),
                "pcs_discharge": bool(g("isPcsDischgEn")),
                "kw_rate_power": g("kwRatePower"),           # -1 = unlimited
                "grid_soft_limit": g("gridSoftLimit"),        # -1 = unlimited (import)
                "grid_hard_limit": g("gridHardLimit"),        # -1 = unlimited (export)
            },
            "inverter": {
                "max_charge_kw": (round(chg_w / 1000, 2) if chg_w else None),
                "max_discharge_kw": (round(dis_w / 1000, 2) if dis_w else None),
                "source": ("Modbus SunSpec 702" if chg_w else None),
                "fhp_rate_power_1701": g("fhpRatePower"),      # reads 0 on this firmware — not the source
            },
        }

    def _cloud_power_control_crosscheck(gateway: str | None = None):
        """Independent WITNESS for a 1701 grid-limit write: the cloud's GLOBAL grid caps
        (globalGridChargeMax/DischargeMax, -1=unlimited). Best-effort — only when cloud creds
        exist AND the optional franklinwh-cloud lib is installed. NB a DIFFERENT storage plane
        (proven not to sync from local 1701), so it's context, not proof."""
        s = get_settings()
        if not (s.fwh_cloud_email and s.fwh_cloud_password):
            return {"available": False, "reason": "no cloud credentials"}
        try:
            from . import cloud_status
            pcs = cloud_status.read_power_control(
                s.fwh_cloud_email, s.fwh_cloud_password, s.fwh_cloud_gateway or None)
            log.debug("cloud call ok: get_power_control_settings")
            return {"available": True, "settings": pcs,
                    "note": "cloud GLOBAL caps — a separate plane; need not reflect a local 1701 write"}
        except Exception as e:  # noqa: BLE001 — the witness is optional; never fail the write
            log.warning("cloud call failed: get_power_control_settings — %s: %s", type(e).__name__, e)
            return {"available": False, "reason": f"{type(e).__name__}: {e}"}

    @app.post("/api/grid/limits")
    def api_set_grid_limits(req: GridLimitsReq, gateway: str | None = Query(None)):
        """Write the 1701 grid import/export power-plane limits (the FWHAI PCS modal) by
        full-block read-modify-write with a self-verifying read-back. **UNVERIFIED local
        write** — see client.set_grid_limits. ``dry_run`` previews the exact frame. A real
        write needs ``confirm`` (428 otherwise) and is audited; when cloud creds exist it also
        returns the cloud global caps as an independent witness."""
        host = _gw_host(gateway)   # SAFETY: the write must hit the SELECTED gateway
        changes: dict = {}
        if req.grid_soft_limit is not None: changes["gridSoftLimit"] = req.grid_soft_limit
        if req.grid_hard_limit is not None: changes["gridHardLimit"] = req.grid_hard_limit
        if req.kw_rate_power is not None:   changes["kwRatePower"] = req.kw_rate_power
        if req.export_enable is not None:   changes["gridExportEnable"] = 1 if req.export_enable else 0
        if req.pcs_discharge is not None:   changes["isPcsDischgEn"] = 1 if req.pcs_discharge else 0
        if not changes:
            raise HTTPException(status_code=400, detail="no grid-limit fields to change")
        if not req.dry_run:
            _guard_consequential(req.confirm, "set grid import/export limits (UNVERIFIED write)")
        try:
            out = client.set_grid_limits(get_settings(), changes, host=host, dry_run=req.dry_run)
        except (OSError, TransportError, TimeoutError, ValueError) as e:
            if not req.dry_run:
                _audit("set_grid_limits", gateway=gateway, detail=str(changes), result=str(e), ok=False)
            raise HTTPException(status_code=502, detail=str(e))
        if req.cloud_crosscheck:
            out["cloud"] = _cloud_power_control_crosscheck(gateway)
        if not req.dry_run:
            _audit("set_grid_limits", gateway=gateway, detail=str(changes),
                   result=("ok" if out.get("ok") else "unverified/mismatch"), ok=bool(out.get("ok")))
        return out

    @app.get("/api/tariff/spot")
    def api_tariff_spot(region: str | None = Query(None)):
        """Live dynamic-tariff price — the two providers in one view (see FEAT-BILLING-WHOLESALE):
        the AusNEM built-in (AEMO NEM regional spot, c/kWh) and an HA price entity. Reports each
        plus the ACTIVE source (HA entity wins over NEM when both are configured), and the exposed
        HA entities so the picker can offer them. Region defaults to the configured nem_region."""
        from . import aemo_nem
        st = get_settings()
        reg = (region or st.nem_region or "").upper()
        spot = aemo_nem.spot_price(reg) if reg else None
        # HA price provider (buy/sell in c/kWh) from the configured entities. Guarded: a store
        # or HA outage must not fail the endpoint — the AusNEM half still answers.
        ha_snap, ha_options = {}, []
        try:
            store = _ha_store()
            ha_snap = scheduler.ha_price_snapshot(st, store)
            ha_options = scheduler.ha_sensor_options(store)
        except Exception:  # noqa: BLE001
            pass
        ha = {
            "price_entity": st.tariff_price_entity or None,
            "feedin_entity": st.tariff_feedin_entity or None,
            "buy_c_kwh": ha_snap.get("tariff.spot_price"),
            "sell_c_kwh": ha_snap.get("tariff.feed_in_price"),
        }
        # Active source: HA entity if it resolved a buy price, else NEM if a spot exists
        if ha["buy_c_kwh"] is not None:
            active = {"source": "ha-entity", "buy_c_kwh": ha["buy_c_kwh"], "sell_c_kwh": ha["sell_c_kwh"]}
        elif spot:
            active = {"source": "nem", "buy_c_kwh": spot.get("price_c_kwh"), "sell_c_kwh": None}
        else:
            active = {"source": None, "buy_c_kwh": None, "sell_c_kwh": None}
        return {"region": reg or None, "regions": list(aemo_nem.REGIONS),
                "configured_region": st.nem_region or None, "spot": spot,
                "ha": ha, "ha_options": ha_options,
                "billing_dynamic": bool(st.billing_dynamic),
                "active": active}

    @app.get("/api/host/timezone")
    def api_host_timezone():
        """The INTEGRATION-HOST timezone (the bridge process's own zone: TZ env / /etc/localtime).
        Used for the bridge's system-of-record — audit trail, app logs, notification log,
        scheduler activity log, connection observations. Defaults to UTC unless TZ is set on the
        container. See docs/TIMEZONES.md."""
        now = _dt.datetime.now().astimezone()
        off = int(now.utcoffset().total_seconds() // 60) if now.utcoffset() else 0
        h, m = divmod(abs(off), 60)
        return {"available": True, "offset_minutes": off,
                "label": f"UTC{'+' if off >= 0 else '-'}{h}" + (f":{m:02d}" if m else ""),
                "tz_name": (now.tzname() or None), "host_time": now.strftime("%Y-%m-%d %H:%M:%S")}

    @app.get("/api/site/timezone")
    def api_site_timezone(gateway: str | None = Query(None)):
        """The SITE's timezone from the aGate (1201), so charts show aGate-local time — not the
        browser's (which may be in a different country). The authoritative offset is the aGate's
        own wall-clock minus UTC (DST-correct); ``timezoneStr`` is usually empty so we don't rely
        on an IANA name. Falls back to the ``timezone`` base-offset hours if the time won't parse."""
        host = _gw_host(gateway)
        try:
            tl = client.read(get_settings(), "time_location", host=host)
        except (OSError, TransportError, TimeoutError, ValueError):
            return {"available": False}
        out = {"available": False, "agate_time": tl.get("time"),
               "base_offset_h": tl.get("timezone"), "dst": tl.get("DST"),
               "tz_str": (tl.get("timezoneStr") or None)}
        t = tl.get("time")
        if t:
            try:
                local = _dt.datetime.strptime(t, "%Y-%m-%d %H:%M:%S")
                off = round((local - _dt.datetime.utcnow()).total_seconds() / 60 / 15) * 15
                out["offset_minutes"] = int(off)
                h, m = divmod(abs(int(off)), 60)
                out["label"] = f"UTC{'+' if off >= 0 else '-'}{h}" + (f":{m:02d}" if m else "")
                out["available"] = True
            except (ValueError, TypeError):
                pass
        if not out["available"] and isinstance(tl.get("timezone"), (int, float)):
            off = int(tl["timezone"]) * 60
            out.update(offset_minutes=off, available=True,
                       label=f"UTC{'+' if off >= 0 else '-'}{abs(int(tl['timezone']))}")
        return out

    # -- gated control writes (off unless allow_writes) -----------------------
    def _guard_writes():
        if not client.writes_enabled(get_settings()):
            raise HTTPException(status_code=403,
                                detail="writes are disabled (set allow_writes to enable)")

    def _guard_consequential(confirm: bool, action: str):
        """The global write-gate is gone; the physically consequential actions
        (operating-mode change, off-grid) instead require an explicit confirm — a
        428 the FWHAI-style confirm dialog satisfies. Not cosmetic: a raw API call
        without confirm is refused."""
        if not confirm:
            raise HTTPException(
                status_code=428,
                detail=f"'{action}' changes the physical gateway — re-send with confirm=true.")

    def _audit(action: str, *, gateway: str | None = None, detail: str = "",
               result: str = "", ok: bool | None = None) -> None:
        """Record one consequential control to BOTH the Audit Trail (structured, on the
        Control tab) and the app Logs stream (so every UI-initiated write is visible in
        one place). Never raises — auditing must never break a control action."""
        # 1 · app Logs — one line per action, WARNING on a known failure else INFO.
        try:
            msg = action + (f" · {detail}" if detail else "") + (f" → {result}" if result else "")
            (log.warning if ok is False else log.info)("control: %s", msg)
        except Exception:  # pragma: no cover
            pass
        # 2 · structured Audit Trail.
        try:
            store = db.get_store(get_settings())
            if store is not None:
                store.log_control_event(action, gateway_id=gateway, source="ui",
                                        detail=detail, result=str(result)[:200], ok=ok)
        except Exception:  # pragma: no cover — auditing must never break a control
            pass

    @app.post("/api/mode")
    def api_set_mode(req: ModeReq, gateway: str | None = Query(None)):
        _guard_consequential(req.confirm, "set operating mode")
        host = _gw_host(gateway)   # SAFETY: the write must hit the SELECTED gateway
        try:
            res = client.set_mode(get_settings(), req.mode, host=host)
            _audit("set_mode", gateway=gateway, detail=f"mode={req.mode}",
                   result=res, ok=bool(res.get("ok", True)) if isinstance(res, dict) else True)
            return res
        except (OSError, TransportError, TimeoutError, ValueError) as e:
            _audit("set_mode", gateway=gateway, detail=f"mode={req.mode}", result=str(e), ok=False)
            raise HTTPException(status_code=502, detail=str(e))

    @app.post("/api/offgrid")
    def api_set_offgrid(req: OffgridReq, gateway: str | None = Query(None)):
        _guard_consequential(req.confirm, "go off-grid / reconnect")
        host = _gw_host(gateway)   # SAFETY: the write must hit the SELECTED gateway
        action = "go_off_grid" if req.on else "reconnect_grid"
        detail = f"restore_soc={req.soc}%" if req.on else "reconnect to grid"
        try:
            res = client.set_offgrid(get_settings(), req.on, req.soc, host=host)
            _audit(action, gateway=gateway, detail=detail, result=res,
                   ok=bool(res.get("ok", True)) if isinstance(res, dict) else True)
            return res
        except (OSError, TransportError, TimeoutError) as e:
            _audit(action, gateway=gateway, detail=detail, result=str(e), ok=False)
            raise HTTPException(status_code=502, detail=str(e))

    @app.get("/api/control-log")
    def api_control_log(limit: int = 100, gateway: str | None = Query(None),
                        action: str | None = Query(None)):
        """The control audit trail — consequential actions (off-grid / reconnect / reboot /
        mode / Modbus toggle), newest first. Read-only; empty list when the store is off."""
        try:
            store = db.get_store(get_settings())
            rows = store.control_log(limit=limit, gateway_id=gateway, action=action) if store else []
        except Exception:  # pragma: no cover
            rows = []
        return {"events": rows}

    @app.get("/api/modbus")
    def api_modbus_get():
        """Modbus (SunSpec 502) master switch + why it is / isn't usable. Live port-502
        reachability is already in the dashboard summary (``modbus_502``), so the UI reads
        that; this endpoint owns the enable flag."""
        from . import battery_control
        ok, why = battery_control.available()
        base = _modbus_host()
        eff_host, eff_port = battery_control.effective_target(base)
        ov = battery_control.host_override()
        return {"enabled": battery_control.is_enabled(), "available": ok, "reason": why,
                "resolved_host": eff_host or None, "resolved_port": eff_port,
                "unit_id": battery_control.UNIT_ID,
                "host_override": ov["host"] or "", "port_override": ov["port"],
                "auto": not ov["host"]}

    @app.put("/api/modbus")
    def api_modbus_put(req: ModbusToggleReq):
        """Enable/disable the direct-Modbus path (ratings + force dispatch). Persisted."""
        from . import battery_control
        store = None
        try:
            store = db.get_store(get_settings())
        except Exception:  # pragma: no cover
            store = None
        if req.enabled is not None:
            battery_control.set_enabled(req.enabled)
            if store is not None:
                store.set_config("modbus_enabled", "1" if req.enabled else "0")
            _audit("modbus_toggle", detail=f"enabled={req.enabled}",
                   result="on" if req.enabled else "off", ok=True)
        if req.host_override is not None or req.port_override is not None:
            host_ov = (req.host_override or "").strip()
            port_ov = int(req.port_override or 0)
            battery_control.set_host_override(host_ov, port_ov)
            if store is not None:
                store.set_config("modbus_host_override", host_ov)
                store.set_config("modbus_port_override", str(port_ov or ""))
            _audit("modbus_host_override", detail=f"host={host_ov!r} port={port_ov or 502}",
                   result="set" if host_ov else "cleared", ok=True)
        ov = battery_control.host_override()
        base = _modbus_host()
        eff_host, eff_port = battery_control.effective_target(base)
        return {"enabled": battery_control.is_enabled(),
                "resolved_host": eff_host or None, "resolved_port": eff_port,
                "host_override": ov["host"] or "", "port_override": ov["port"],
                "auto": not ov["host"]}

    @app.post("/api/modbus/test")
    def api_modbus_test():
        """Live connect to the resolved Modbus target and report reachability + ratings."""
        from . import battery_control
        base = _modbus_host()
        eff_host, eff_port = battery_control.effective_target(base)
        target = f"{eff_host}:{eff_port}" if eff_host else None
        if not eff_host:
            return {"ok": False, "target": None, "reason": "no gateway host to reach over Modbus"}
        st = battery_control.status(base)   # live connect; applies the override via effective_target
        return {"ok": bool(st.get("available")), "target": target,
                "reason": st.get("reason") or "",
                "max_charge_w": st.get("max_charge_w"),
                "max_discharge_w": st.get("max_discharge_w")}

    # -- cloud-aligned facade WRITES ------------------------------------------
    # Mirror franklinwh-cloud's write-method contracts, translated to local cmdTypes,
    # so FWHAI can call the bridge first and fall back to the Cloud API. All gated by
    # allow_writes (403 when off); device errors → 502 (never 500).
    @app.post("/api/cloud/set-mode")
    def api_cloud_set_mode(req: SetModeReq, gateway: str | None = Query(None)):
        """Cloud ``set_mode``. Maps requestedOperatingMode (cloud workMode 1=Time-of-Use /
        2=Self-Consumption / 3=Emergency Backup, or a name/alias) to the local mode write
        (1727). Reserve SOC is cloud-owned; backup-forever / next-mode / duration are
        cloud-only — any provided are surfaced in ``not_applied_locally`` (honest partial
        success), NOT silently pretended-applied."""
        _guard_consequential(req.confirm, "set operating mode (cloud)")
        host = _gw_host(gateway)   # SAFETY: the write must hit the SELECTED gateway
        local_mode, _wm = _resolve_cloud_mode(req.requestedOperatingMode)
        try:
            result = client.set_mode(get_settings(), local_mode, host=host)
        except (OSError, TransportError, TimeoutError, ValueError) as e:
            raise HTTPException(status_code=502, detail=str(e))
        not_applied = [name for name, val in (
            ("requestedSOC", req.requestedSOC),
            ("reqbackupForeverFlag", req.reqbackupForeverFlag),
            ("reqnextWorkMode", req.reqnextWorkMode),
            ("reqdurationMinutes", req.reqdurationMinutes),
        ) if val is not None]
        out = dict(result)
        out["not_applied_locally"] = not_applied
        if not_applied:
            out["note"] = ("reserve SOC is cloud-owned (the local API silently discards it); "
                           "backup-forever / next-mode / duration are cloud-only — set these "
                           "via the Cloud API. The operating-mode switch above was applied "
                           "locally.")
        return out

    @app.post("/api/cloud/grid-status")
    def api_cloud_grid_status(req: GridStatusReq, gateway: str | None = Query(None)):
        """Cloud ``set_grid_status``. Parses ``status`` against the cloud GridStatus
        names/values (NORMAL=0 / DOWN=1 / OFF=2); ``on = status != NORMAL`` → local
        set_offgrid (1723) with ``soc`` as the off-grid floor."""
        _guard_writes()
        host = _gw_host(gateway)   # SAFETY: the write must hit the SELECTED gateway
        try:
            value = _grid_status_value(req.status)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        try:
            return client.set_offgrid(get_settings(), value != 0, req.soc, host=host)
        except (OSError, TransportError, TimeoutError) as e:
            raise HTTPException(status_code=502, detail=str(e))

    @app.post("/api/cloud/smart-circuit/state")
    def api_cloud_smart_circuit_state(req: SmartCircuitStateReq,
                                      gateway: str | None = Query(None)):
        """Cloud ``set_smart_circuit_state`` → local 1409 full-block read-modify-write.
        Read-back self-verified: ``ok`` is True only when the re-read confirms the mode
        flipped. The write path was live-verified on a real aGate (2026-08-08: Sw2 toggled
        0→1→0, read-back confirmed each time). ``confirmed`` is THIS call's read-back and
        may be false on a delayed-apply — re-read to confirm."""
        _guard_writes()
        host = _gw_host(gateway)   # SAFETY: the write must hit the SELECTED gateway
        try:
            result = client.set_smart_circuit(get_settings(), req.circuit, req.turn_on,
                                              host=host)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        except (OSError, TransportError, TimeoutError) as e:
            raise HTTPException(status_code=502, detail=str(e))
        out = dict(result)
        out["hardware_verified"] = True   # write mechanism proven on live hardware (2026-08-08)
        out["hardware_note"] = ("write path live-verified on a real aGate; 'confirmed' is "
                                "this call's 1409 read-back (may be false on delayed-apply). "
                                "NB: SwXMode toggles the config flag — power only flows on a "
                                "circuit with a physical load (a bare/'test' switch reads 0 V).")
        return out

    _WORKMODE_NAME = {1: "tou", 2: "self", 3: "backup"}

    def _require_cloud() -> dict:
        """Refuse a cloud-dependent call unless the credentials are known good.

        Without this a missing or wrong credential surfaces as a generic transport
        error, which reads like the feature is broken rather than not connected.
        The rule matches the UI: cloud features exist only while cloud auth is valid.
        """
        auth = providers.cloud_auth_status()
        state = auth.get("state")
        if state == "valid":
            return auth
        why = {
            "unconfigured": "no cloud credentials are configured",
            "locked": "cloud login is locked after repeated failures — "
                      "re-enter the credentials to clear it",
            "invalid": f"cloud credentials were rejected: {auth.get('error') or ''}",
            "unknown": "cloud credentials have not been checked yet — press Test",
        }.get(state, f"cloud is not connected ({state})")
        raise HTTPException(status_code=503, detail=f"Cloud not connected — {why}.")

    @app.get("/api/capabilities")
    def api_capabilities():
        """What this bridge can actually do right now, and why not where it cannot.

        Local features are always available. Cloud features exist ONLY while the
        cloud credentials are valid — the UI uses this to disable them with a
        reason rather than offering a control that will fail.
        """
        auth = providers.cloud_auth_status()
        cloud_ok = auth.get("state") == "valid"
        cloud_why = None if cloud_ok else {
            "unconfigured": "No cloud credentials configured.",
            "locked": "Cloud login locked after repeated failures.",
            "invalid": "Cloud credentials were rejected.",
            "unknown": "Cloud credentials not checked yet.",
        }.get(auth.get("state"), "Cloud not connected.")
        return {
            "local": {
                # Every one of these is hardware-verified on this firmware.
                "set_mode": True,
                "smart_circuit_switch": True,
                "generator_config": True,
                "offgrid": True,
                "reboot": True,
            },
            "cloud": {
                "connected": cloud_ok,
                "state": auth.get("state"),
                "reason": cloud_why,
                "reserve_soc": cloud_ok,
                "tou_schedule": cloud_ok,
                "force_charge_discharge": cloud_ok,
            },
            # Proven impossible locally — probed, not assumed. Kept here so the UI
            # can explain rather than silently omit.
            "unavailable_locally": {
                "reserve_soc": "1405/1725/1727 accept the write and discard it",
                "tou_schedule": "1407 accepts the write and discards it",
                "smart_circuit_schedule": "1409 accepts the schedule write and discards it",
                "force_charge_discharge": "no dispatchId/gridChargeMax field exists locally",
            },
        }

    @app.post("/api/cloud/reserve")
    def api_cloud_reserve(req: ReserveReq, gateway: str | None = Query(None)):
        """Set a mode's reserve SoC via the CLOUD provider (HYBRID Phase 3) — the local API
        silently discards this write (reserve is cloud-owned), so it routes to the cloud
        ``updateSocV2``. Gated by allow_writes. 503 = no cloud provider configured · 501 =
        FWHAI path not wired · 422 = bad mode/soc · 502 = cloud unreachable/error."""
        _guard_writes()
        _require_cloud()
        mode = req.mode or _WORKMODE_NAME.get(req.workMode)
        soc = req.soc if req.soc is not None else req.requestedSOC
        if not mode or soc is None:
            raise HTTPException(status_code=422,
                                detail="provide mode (self/tou/backup) + soc")
        detail = f"mode={mode} soc={soc}% (cloud updateSocV2)"
        try:
            out = providers.set_reserve(get_settings(), mode, soc)
            _audit("set_reserve", gateway=gateway, detail=detail,
                   result=(out.get("note") if isinstance(out, dict) else None) or "applied via cloud",
                   ok=bool(out.get("ok", True)) if isinstance(out, dict) else True)
            return out
        except providers.ReserveUnavailable as e:
            _audit("set_reserve", gateway=gateway, detail=detail, result=f"no cloud provider: {e}", ok=False)
            raise HTTPException(status_code=503, detail=str(e))
        except ValueError as e:
            _audit("set_reserve", gateway=gateway, detail=detail, result=f"invalid: {e}", ok=False)
            raise HTTPException(status_code=422, detail=str(e))
        except NotImplementedError as e:
            _audit("set_reserve", gateway=gateway, detail=detail, result=f"not wired: {e}", ok=False)
            raise HTTPException(status_code=501, detail=str(e))
        except Exception as e:  # noqa: BLE001 — cloud transport/auth failure
            _audit("set_reserve", gateway=gateway, detail=detail, result=f"cloud error: {e}", ok=False)
            raise HTTPException(status_code=502, detail=f"cloud reserve write failed: {e}")

    @app.post("/api/cloud/validate")
    def api_cloud_validate():
        """Check the stored cloud credentials with ONE login + a permissioned read.

        Never auto-retried here — this is the explicit user action. Honours the
        breaker: after ``_MAX_AUTH_FAILS`` consecutive failures it refuses to attempt
        and returns ``state="locked"`` so a wrong password cannot be hammered into an
        account lock. Change the credentials (or PUT them again) to clear it.

        Returns the auth snapshot: ``state``, ``error``, ``checked_at``, ``age_s``,
        ``stale``, ``fail_count``, ``max_fails``. Not a write to the device, so it is
        deliberately NOT behind allow_writes.
        """
        out = providers.validate_cloud(get_settings())
        # A cloud API call made from a UI control — surface it on the Logs screen.
        state = (out or {}).get("state")
        err = (out or {}).get("error")
        msg = f"cloud credential check → {state}" + (f" ({err})" if err else "")
        (log.warning if state in ("invalid", "locked", "error") else log.info)("control: %s", msg)
        return out

    @app.get("/api/battery")
    def api_battery(gateway: str | None = Query(None),
                    id: int = Query(1, ge=1, le=32)):
        """Full BMS view for one aPower in a SINGLE aGate session.

        Cells (1705) + electrical (1703) + states (1835) + firmware (1833) + unit list
        (1105). Calling the four /api/cmd/* endpoints separately would open four
        sessions against a slow device on flaky wifi. Sub-reads are best-effort: a
        failed block is null with the reason under `errors`, so a marginal link still
        yields partial telemetry.

        `id` selects the aPower (devMap[].id from device_check).
        """
        return _read(lambda s, host: client.battery(s, host, id), gateway)

    # -- BMS recording sessions ----------------------------------------------
    # A bounded burst of full per-cell snapshots, persisted for later charting.
    # Runs in a background thread, NOT the poll loop: it samples far faster than
    # the 30s poll and must not perturb the long-run history.
    @app.post("/api/battery/record")
    def api_bms_record(req: BmsRecordReq, gateway: str | None = Query(None)):
        """Start a recording session. 409 if one is already running, 422 on bad
        parameters, 503 if metrics storage is disabled."""
        store = db.get_store(get_settings())
        if store is None:
            raise HTTPException(status_code=503,
                                detail="metrics storage is disabled (METRICS_ENABLED)")
        host = _gw_host(gateway)
        sn = None
        try:
            sn = ((client.battery(get_settings(), host, req.id).get("firmware") or {})
                  .get("fhp_sn"))
        except Exception:  # noqa: BLE001 — the serial is a label, not a requirement
            pass

        def _fetch():
            return client.battery(get_settings(), host, req.id).get("cells")

        try:
            return bms_record.get_recorder().start(
                store, _fetch, samples=req.samples, interval_s=req.interval_s,
                gateway_id=gateway, apower_sn=sn, dev_id=req.id, label=req.label)
        except ValueError as e:
            code = 409 if "already running" in str(e) else 422
            raise HTTPException(status_code=code, detail=str(e))

    @app.post("/api/battery/record/stop")
    def api_bms_record_stop():
        """Finish the running session early. Safe to call when none is active."""
        return bms_record.get_recorder().stop()

    @app.get("/api/battery/record/status")
    def api_bms_record_status():
        """Progress of the running (or last) session: captured / planned / errors."""
        return bms_record.get_recorder().status()

    @app.get("/api/battery/sessions")
    def api_bms_sessions(limit: int = Query(200, ge=1, le=1000),
                         apower: str | None = Query(None)):
        """Recorded sessions, newest first, with real sample counts and spans."""
        store = db.get_store(get_settings())
        return {"sessions": store.bms_sessions(limit, apower) if store else []}

    @app.get("/api/battery/sessions/{session_id}")
    def api_bms_session(session_id: int):
        """One session with every snapshot, cell arrays parsed to lists."""
        store = db.get_store(get_settings())
        out = store.bms_session(session_id) if store else None
        if out is None:
            raise HTTPException(status_code=404, detail="no such session")
        return out

    @app.delete("/api/battery/sessions/{session_id}")
    def api_bms_session_delete(session_id: int):
        store = db.get_store(get_settings())
        if store is None or not store.delete_bms_session(session_id):
            raise HTTPException(status_code=404, detail="no such session")
        return {"ok": True, "deleted": session_id}

    # -- field-schema + command catalog (labelling metadata) ------------------
    # Static, no device I/O — the UI loads these once to label + group raw fields
    # (Device tab + dashboard Live Points) without hardcoding anything client-side.
    @app.get("/api/schema")
    def api_schema():
        """Reverse index ``raw_key -> {label, group, unit}`` (ported field schema).
        Used by the Device tab and Live Points to label/group raw device fields."""
        return fieldschema.FIELD_SCHEMA

    @app.get("/api/catalog")
    def api_catalog():
        """What each /api/cmd/<name> endpoint IS: ``name -> {description, cmd, write}``
        from ``franklinwh_local.catalog``. ``write`` marks cmdTypes with a known write
        recipe (catalog.WRITES). Never raises — degrades to {} on any import/attr error."""
        try:
            from franklinwh_local import catalog as _cat
            write_cmds = {w.get("cmd") for w in getattr(_cat, "WRITES", {}).values()}
            out: dict[str, dict] = {}
            for info in _cat.CATALOG.values():
                out[info.name] = {
                    "description": info.description,
                    "cmd": info.request,
                    "write": info.request in write_cmds,
                }
            return out
        except Exception as e:  # never 500 — the catalog is optional metadata
            log.warning("catalog build failed: %s", e)
            return {}

    # -- full raw read surface: one GET per LocalClient read method ------------
    # Registered in a loop (closure factory avoids late-binding) so OpenAPI lists
    # every /api/cmd/<name> individually. Live, on-demand reads — never auto-polled.
    for _name in sorted(client.READ_METHODS):
        def _mk(nm):
            def handler(response: Response, gateway: str | None = Query(None)):
                host = _gw_host(gateway)
                try:
                    payload, sent = client.read_with_request(get_settings(), nm, host=host)
                    # Provenance in a HEADER, not the body: the reading must stay
                    # exactly what the gateway returned so the table, JSON and CSV
                    # views are not polluted by bridge metadata.
                    if sent:
                        response.headers["X-FWH-Request"] = _json.dumps(
                            sent, separators=(",", ":"))
                    return payload
                except (OSError, TransportError, TimeoutError) as e:
                    raise HTTPException(status_code=502, detail=str(e))
                except ValueError as e:
                    raise HTTPException(status_code=404, detail=str(e))
            return handler
        app.add_api_route(f"/api/cmd/{_name}", _mk(_name), methods=["GET"],
                          name=f"cmd_{_name}", summary=f"Read {_name} (live)")

    # -- generic passthrough --------------------------------------------------
    @app.post("/api/call/{cmd}")
    def api_call(cmd: int, req: CallReq, gateway: str | None = Query(None)):
        """Issue any request cmdType with a dataArea of {opt, **data}. opt != 0 is a write
        and requires allow_writes."""
        if req.opt != 0:
            _guard_writes()
        host = _gw_host(gateway)
        data_area = {"opt": req.opt, **req.data}
        try:
            return client.call(get_settings(), cmd, data_area, host=host)
        except (OSError, TransportError, TimeoutError) as e:
            raise HTTPException(status_code=502, detail=str(e))

    # -- extra gated writes ---------------------------------------------------
    @app.post("/api/der-comms")
    def api_set_der_comms(req: DerCommsReq, gateway: str | None = Query(None)):
        """Write DER comms toggles (SunSpec Modbus / IEEE 2030.5). Delayed-apply — the
        device reply is not proof; verify at the interface level (:502 / status2030_5)."""
        _guard_writes()
        host = _gw_host(gateway)   # SAFETY: the write must hit the SELECTED gateway
        try:
            return client.set_der_comms(get_settings(),
                                        sunspec_modbus=req.sunspec_modbus,
                                        ieee2030_5=req.ieee2030_5, host=host)
        except (OSError, TransportError, TimeoutError) as e:
            raise HTTPException(status_code=502, detail=str(e))

    @app.post("/api/reboot")
    def api_reboot(req: RebootReq, gateway: str | None = Query(None)):
        """DESTRUCTIVE — reboot the aGate. Double-gated (allow_writes + confirm=true). The
        gateway drops the connection while it restarts and may trigger 4G failover."""
        _guard_writes()
        host = _gw_host(gateway)   # SAFETY: the write must hit the SELECTED gateway
        if not req.confirm:
            raise HTTPException(status_code=400, detail="reboot requires confirm=true")
        try:
            res = client.reboot(get_settings(), host=host)
            _audit("reboot_gateway", gateway=gateway, detail="restart aGate", result=res,
                   ok=bool(res.get("ok", True)) if isinstance(res, dict) else True)
            return res
        except (OSError, TransportError, TimeoutError) as e:
            # The link drops as it restarts — a transport error here is expected; record
            # the request as sent (the reboot very likely took effect).
            _audit("reboot_gateway", gateway=gateway, detail="restart aGate",
                   result=f"link dropped (expected): {e}", ok=None)
            raise HTTPException(status_code=502, detail=str(e))

    @app.post("/api/dispatch")
    def api_dispatch(req: DispatchReq):
        """HYBRID-CAPABILITIES Phase 2 — battery dispatch (force charge/discharge/standby/
        release, target-SoC) via the resolved Modbus provider. This is a HARD WALL for the
        local API, so it delegates to an installed Modbus Bridge (whose watchdog makes it
        safe). Gated by allow_writes. 503 = no provider, 501 = library path not wired,
        422 = bad action, 502 = provider unreachable."""
        _guard_writes()
        try:
            return providers.dispatch(
                get_settings(), req.action, power_w=req.power_w, power_pct=req.power_pct,
                duration_s=req.duration_s, target_soc=req.target_soc)
        except providers.DispatchUnavailable as e:
            raise HTTPException(status_code=503, detail=str(e))
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        except NotImplementedError as e:
            raise HTTPException(status_code=501, detail=str(e))
        except (OSError, TimeoutError) as e:
            raise HTTPException(status_code=502, detail=f"dispatch provider unreachable: {e}")

    # -- MQTT tab -------------------------------------------------------------
    @app.get("/api/mqtt/config")
    def api_mqtt_config(gateway: str | None = Query(None)):
        s = get_settings()
        gw = _gw_or_404(gateway)
        return {
            "connected": gw.mqtt_connected,
            "enabled": s.mqtt_enabled,
            "host": s.mqtt_host,
            "port": s.mqtt_port,
            "prefix": s.mqtt_prefix,
            "discovery_prefix": s.ha_discovery_prefix,
        }

    @app.get("/api/mqtt/conflicts")
    def api_mqtt_conflicts(gateway: str | None = Query(None)):
        """Scan the shared broker for OTHER FranklinWH producers (a Modbus bridge, FWHAI, or a
        second Local bridge). On a shared broker each producer names the aGate under its own
        node, so the SAME device shows up as duplicate HA cards — this surfaces them (and any
        true identifier collision) so setup can warn. Read-only; ~2.5s broker sniff."""
        from .publish import mqtt_scan
        s = get_settings()
        if not s.mqtt_enabled:
            return {"ok": False, "error": "MQTT publishing is disabled — enable it to scan the broker"}
        gw = _gw_or_404(gateway)
        own_node = getattr(gw, "node", None) or (getattr(gw, "serial", "") or "agate").lower()
        return mqtt_scan.scan_conflicts(s, own_node)

    def _live_nodes() -> list[str]:
        """Every node id this bridge currently publishes — the keep-list for a purge.
        Covers all gateways, not just the selected one, so a multi-gateway install
        cannot have one gateway's purge delete another's entities."""
        out = []
        for g in get_gateways():
            n = getattr(g, "node", None) or (getattr(g, "serial", "") or "")
            if n:
                out.append(str(n).lower())
        return out

    @app.get("/api/health/workers")
    def api_health_workers():
        """Every DECLARED background worker: state, liveness, restart safety (BR-38).

        Declared, not discovered: enumerating raw asyncio tasks would fill this with
        framework plumbing and bury the three rows that matter. Anything doing
        background work without appearing here is itself the bug.

        `ok` is false when any worker is failed or has stopped beating. It does NOT
        feed /api/live — a failed worker deliberately does not fail the container
        (RUNTIME_DESIGN decision 4), because restarting the world hides the cause."""
        return _workers.registry.snapshot()

    def _dispatch_guard() -> str:
        """Why restarting the dispatch watchdog is unsafe right now, or "" if it is not.

        This firmware's hardware revert timer is cosmetic, so the software watchdog is
        the only thing that ends a force. Restarting it while one is in flight would
        drop the force's owner — a safety regression wearing a convenience button.
        """
        try:
            cur = battery_control.current()
        except Exception:  # noqa: BLE001 — never let the guard itself fail open
            return "cannot determine dispatch state — refusing"
        if cur and cur.get("command"):
            return (f"force active ({cur.get('command')}) — release it first, or restart "
                    "the bridge so boot reconcile re-adopts it")
        return ""

    @app.post("/api/health/workers/{name:path}/restart")
    def api_worker_restart(name: str):
        """Restart one worker, if that is safe *right now* (BR-37, design §5.4).

        Restartability and restart-safety are different questions: a worker may be
        restartable in principle and blocked at this moment because it is winding down,
        in a crash loop, or holding an in-flight force."""
        _guard_writes()
        w = _workers.registry.get(name)
        if w is None:
            raise HTTPException(404, f"no worker '{name}'")
        block = w.restart_block(guard=_dispatch_guard)
        if block:
            _audit("worker_restart", detail=name, result=f"refused: {block}", ok=False)
            raise HTTPException(409, block)
        try:
            w.note_restart()
            w.factory()
        except Exception as e:  # noqa: BLE001
            _audit("worker_restart", detail=name, result=str(e), ok=False)
            raise HTTPException(500, f"restart failed: {e}")
        _audit("worker_restart", detail=name, result="restarted", ok=True)
        return {"ok": True, "name": name, "restarts": w.restarts}

    @app.get("/api/mqtt/orphans")
    def api_mqtt_orphans():
        """DRY RUN — what a purge would clear, and what it would leave alone.

        Retained discovery configs never expire, so a node this bridge no longer
        publishes (a changed serial, a torn-down mock, the old "agate" fallback)
        leaves Home Assistant re-creating dead entities on every restart. This
        reports them. Publishes NOTHING; ~2.5s broker sniff."""
        from .publish import mqtt_scan
        s = get_settings()
        if not s.mqtt_enabled:
            return {"ok": False, "error": "MQTT publishing is disabled — enable it to scan the broker"}
        return mqtt_scan.scan_orphans(s, _live_nodes())

    @app.post("/api/mqtt/orphans/purge")
    def api_mqtt_orphans_purge(
        expect: int = Query(..., description="orphan count from the dry run; a mismatch refuses"),
        confirm: bool = Query(False, description="must be true — this deletes retained topics"),
    ):
        """Clear this bridge's orphaned discovery configs. Destructive and audited.

        Two guards, because the broker is shared and a wrong ownership test would
        delete the Modbus bridge's or FWHAI's entities:
          * ``confirm=true`` must be passed explicitly;
          * ``expect`` must equal the orphan count a fresh scan finds, so the
            operator cannot confirm one set and have a different set deleted.
        Only configs whose device sw_version carries this bridge's own prefix are
        ever touched."""
        from .publish import mqtt_scan
        s = get_settings()
        if not s.mqtt_enabled:
            return {"ok": False, "error": "MQTT publishing is disabled"}
        if not confirm:
            return {"ok": False, "error": "refused: pass confirm=true — this clears retained "
                                          "discovery topics and cannot be undone from here"}
        res = mqtt_scan.purge_orphans(s, _live_nodes(), expect=expect)
        _audit("mqtt_purge_orphans",
               detail=f"expect={expect} cleared={res.get('cleared', 0)}",
               result=res.get("detail") or res.get("error", ""),
               ok=bool(res.get("ok")))
        return res

    def _mqtt_groups(store) -> list:
        """Enabled MQTT publish groups (global preference). Defaults when unset."""
        if store is None:
            return entities.default_groups()
        try:
            raw = store.get_config("mqtt_groups")
            g = _json.loads(raw) if raw else None
            return [x for x in g if x in entities.GROUPS] if isinstance(g, list) else entities.default_groups()
        except Exception:  # noqa: BLE001
            return entities.default_groups()

    @app.get("/api/mqtt/groups")
    def api_mqtt_groups():
        """The publish-group catalogue + which are enabled (opt-in optional data)."""
        return {"groups": entities.GROUPS, "enabled": _mqtt_groups(_gw_store()),
                "default": entities.default_groups()}

    @app.put("/api/mqtt/groups")
    def api_mqtt_groups_put(req: MqttGroupsBody):
        """Set enabled groups; triggers a re-publish on every gateway so HA reflects it."""
        st = _gw_store()
        if st is None:
            raise HTTPException(503, "metrics store is disabled")
        enabled = [g for g in (req.groups or []) if g in entities.GROUPS]
        st.set_config("mqtt_groups", _json.dumps(enabled))
        for g in get_gateways():
            g.republish_requested = True
        return {"enabled": enabled, "groups": entities.GROUPS}

    @app.get("/api/mqtt/entities")
    def api_mqtt_entities(gateway: str | None = Query(None)):
        """Entities for the SELECTED gateway (multi-gateway; mocks included). Values come
        from that gateway's last poll (so a mock shows its synthetic values); the row set
        reflects the enabled publish groups and includes the writable Controls. `publishing`
        says whether this gateway is actually sending to HA (a mock with publish_ha off is
        listed but not published)."""
        s = get_settings()
        gw = _gw_or_404(gateway)
        node = gw.node or "agate"
        prefix = s.mqtt_prefix
        state_topic = f"{prefix}/{node}/state"
        enabled = set(_mqtt_groups(_gw_store()))
        st = gw.last_state or {}
        rows = []
        for e in entities.ENTITIES:
            g = e.get("group", "core")
            if g not in enabled:
                continue
            rows.append({"slug": e["key"], "name": e["name"], "ha_type": "sensor", "writable": False,
                         "group": g, "diagnostic": g == "diagnostic", "unit": e.get("unit"),
                         "value": st.get(e["key"]), "stat_key": e["key"], "state_topic": state_topic,
                         "command_topic": None, "options": []})
        if "controls" in enabled:
            for c in entities.CONTROLS:
                rows.append({"slug": c["key"], "name": c["name"], "ha_type": c["ha_type"], "writable": True,
                             "group": "controls", "diagnostic": False, "unit": None,
                             "value": st.get(c.get("state_key")), "stat_key": c.get("state_key"),
                             "state_topic": state_topic,
                             "command_topic": f"{prefix}/{node}/control/{c['key']}/set",
                             "options": c.get("options", [])})
        return {"entities": rows, "node": node, "publishing": bool(getattr(gw, "mqtt_connected", False)),
                "enabled_groups": sorted(enabled), "groups": entities.GROUPS}

    @app.post("/api/mqtt/republish")
    def api_mqtt_republish(gateway: str | None = Query(None)):
        s = get_settings()
        gw = _gw_or_404(gateway)
        if not s.mqtt_enabled:
            return {"ok": False, "detail": "MQTT is disabled"}
        gw.republish_requested = True   # the RIGHT gateway's poller re-publishes
        return {"ok": True, "detail": "Re-publishing HA discovery…"}

    @app.post("/api/mqtt/unpublish")
    def api_mqtt_unpublish(gateway: str | None = Query(None)):
        s = get_settings()
        gw = _gw_or_404(gateway)
        if not s.mqtt_enabled:
            return {"ok": False, "detail": "MQTT is disabled"}
        gw.unpublish_requested = True   # the RIGHT gateway's poller clears entities
        return {"ok": True, "detail": "Clearing entities from Home Assistant…"}

    @app.get("/api/mqtt/discover")
    def api_mqtt_discover():
        """Ask the HA Supervisor for the Mosquitto broker's host/port/creds. In add-on
        mode creds are auto-applied at startup; this powers a Settings "Detect broker"
        button. Never 500s — returns {found:false, error} off-Supervisor."""
        return discover_mqtt()

    # -- Notifications verify -------------------------------------------------
    @app.post("/api/notify/test")
    def api_notify_test():
        """Send a test persistent notification through the configured HA target so the
        user can verify notifications end-to-end. Informational — not gated by writes."""
        notifier = Notifier(get_settings())
        if not (notifier.enabled and notifier.token and notifier.base):
            return {"ok": False,
                    "detail": "No notification target configured (HA add-on Supervisor "
                              "token, or ha_url + ha_token for standalone)."}
        try:
            notifier.notify("FranklinWH Direct Connect Bridge",
                            "Test notification from the bridge.")
            return {"ok": True, "detail": "Test notification sent to Home Assistant."}
        except Exception as e:  # noqa: BLE001 — notify already swallows, belt-and-braces
            return {"ok": False, "detail": str(e)}

    # -- Settings tab (read-only, effective config; never returns secrets) -----
    @app.get("/api/settings")
    def api_settings():
        s = get_settings()
        state = get_state()
        return {
            "connection": {
                "host": client.active_host(s),
                "configured_host": s.fwh_host,
                "port": s.fwh_port,
                "timeout": s.fwh_timeout,
                "retries": s.fwh_retries,
                "subnet": s.fwh_subnet,
                "poll_interval": s.poll_interval,
            },
            "cloud": {
                # Credentials for the cloud-owned writes (reserve SoC). The password is
                # never returned — only whether one is set. `auth` carries the breaker
                # state plus how old the last real check is, so the UI can distinguish
                # "valid 30s ago" from "valid last week" (stale=true).
                "email": s.fwh_cloud_email or "",
                "password_set": bool(s.fwh_cloud_password),
                "gateway": s.fwh_cloud_gateway or "",
                "auth": providers.cloud_auth_status(),
            },
            "mqtt": {
                "enabled": s.mqtt_enabled,
                "host": s.mqtt_host,
                "port": s.mqtt_port,
                "username": s.mqtt_username or "",
                "password_set": bool(s.mqtt_password),
                "prefix": s.mqtt_prefix,
                "discovery_prefix": s.ha_discovery_prefix,
                "connected": state.mqtt_connected,
            },
            "control": {
                "read_only": s.read_only,
                # Global write-gate dropped (FEAT-WRITE-CONFIRM); consequential actions
                # confirm at the endpoint. Report open so the UI is writable.
                "allow_writes": client.writes_enabled(get_settings()),
                "log_level": s.log_level,
            },
            "notifications": {
                "ha_notify": s.ha_notify,
                "ha_url": s.ha_url,                      # not secret; the token never is returned
                "ha_token_set": bool(s.ha_token),
                # In the HA add-on the Supervisor token is auto-injected — ha_url/ha_token
                # are not needed. The UI uses this to explain (and de-emphasise) those fields.
                "supervisor": bool(os.environ.get("SUPERVISOR_TOKEN")),
            },
            "metrics": {
                "enabled": metrics_active(s),
                "mode": "explicit" if s.metrics_enabled is not None else "auto",
                "runtime": environment.RUNTIME,
            },
            "environment": {
                "runtime": environment.RUNTIME,
                "is_ha_addon": environment.IS_HA_ADDON,
            },
            "location": {
                "latitude": s.pv_latitude, "longitude": s.pv_longitude,
                "pv_kwp": s.pv_kwp, "pv_tilt": s.pv_tilt, "pv_azimuth": s.pv_azimuth,
            },
            "scheduler": {
                "dispatch_interrupt_policy": s.dispatch_interrupt_policy,
            },
        }

    # -- Settings tab (live write — scoped whitelist, P7) ---------------------
    @app.put("/api/settings")
    async def api_settings_update(request: Request):
        """Live-apply a small whitelist of runtime settings (allow_writes / log_level /
        ha_notify) and persist them to DATA_DIR so they survive a restart. Restart-only
        fields (host / broker / poll_interval / metrics) → 422. Returns the updated view.

        Effects are immediate: toggling ``allow_writes`` flips the write guard on the very
        next request (a runtime kill-switch); ``log_level`` re-levels the bridge logger."""
        editable = ("allow_writes, log_level, ha_notify, ha_url, ha_token, "
                    "fwh_cloud_email, fwh_cloud_password, fwh_cloud_gateway")
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            raise HTTPException(status_code=422, detail="request body must be JSON")
        if not isinstance(body, dict):
            raise HTTPException(status_code=422, detail="request body must be a JSON object")
        from .config import _OVERRIDE_KEYS
        unknown = [k for k in body if k not in _OVERRIDE_KEYS]
        if unknown:
            raise HTTPException(
                status_code=422,
                detail=(f"{', '.join(unknown)} is not live-editable — restart to change "
                        f"(set via env / the add-on Configuration tab). Live-editable "
                        f"keys: {editable}."))
        try:
            req = SettingsUpdate(**body)
        except Exception as e:  # noqa: BLE001 — surface validation as 422, never 500
            raise HTTPException(status_code=422, detail=str(e))
        s = get_settings()
        for key, value in req.model_dump(exclude_unset=True).items():
            if key == "dispatch_interrupt_policy":
                pol = str(value or "").strip().lower()
                if pol not in ("none", "notify", "release", "resume"):
                    raise HTTPException(
                        status_code=422,
                        detail=(f"invalid dispatch_interrupt_policy {value!r}; expected "
                                f"one of none, notify, release, resume"))
                s.dispatch_interrupt_policy = pol
                save_override("dispatch_interrupt_policy", pol)
            elif key == "log_level":
                lvl = str(value or "").strip().lower()
                if lvl not in _LOG_LEVELS:
                    raise HTTPException(
                        status_code=422,
                        detail=(f"invalid log_level {value!r}; expected one of "
                                f"{', '.join(_LOG_LEVELS)}"))
                s.log_level = lvl
                logging.getLogger("franklinwh_direct_connect_bridge").setLevel(_LOG_LEVELS[lvl])
                save_override("log_level", lvl)
            elif key in ("ha_url", "ha_token"):  # standalone HA target — strings
                val = str(value or "")
                setattr(s, key, val)
                save_override(key, val)
            elif key in ("fwh_cloud_email", "fwh_cloud_password", "fwh_cloud_gateway"):
                # Strings, not booleans — the generic branch below would coerce them.
                val = str(value or "").strip()
                if key == "fwh_cloud_gateway":
                    val = val.upper()          # the cloud is case-sensitive on serials
                changed = getattr(s, key, "") != val
                setattr(s, key, val)
                save_override(key, val)
                if changed:
                    # Any credential change invalidates the previous verdict — including a
                    # LOCKED breaker, which is the intended way out of a lockout.
                    providers.reset_cloud_breaker()
            elif key in ("pv_latitude", "pv_longitude", "pv_kwp", "pv_tilt", "pv_azimuth"):
                # Numeric (float) — empty/None clears; the bool branch would coerce it.
                if value in (None, ""):
                    val = None
                else:
                    try:
                        val = float(value)
                    except (TypeError, ValueError):
                        raise HTTPException(status_code=422, detail=f"{key} must be a number")
                setattr(s, key, val)
                save_override(key, val)
            elif key in ("tariff_price_entity", "tariff_feedin_entity"):
                # HA scheduler-id strings (ha:<inst>:<eid>) — not bools; empty clears.
                val = str(value or "").strip()
                setattr(s, key, val)
                save_override(key, val)
            elif key == "nem_region":
                # AEMO NEM region string (not a bool — the generic branch would coerce it).
                from . import aemo_nem
                val = str(value or "").strip().upper()
                if val and val not in aemo_nem.REGIONS:
                    raise HTTPException(status_code=422,
                                        detail=f"nem_region must be one of {', '.join(aemo_nem.REGIONS)} or empty")
                setattr(s, key, val)
                save_override("nem_region", val)
            else:  # allow_writes / ha_notify — booleans
                setattr(s, key, bool(value))
                save_override(key, bool(value))
        return api_settings()

    # -- Logs tab (in-memory ring buffer, P6) ---------------------------------
    @app.get("/api/apower-specs")
    def api_apower_specs(gateway: str | None = Query(None)):
        """aPower model spec table (usable/rated kWh, kW) + the selected gateway's aPower COUNT,
        so the UI can derive battery capacity = usable_kwh × count (the local API can't read the
        model). Count comes from the cached firmware (FHP_SN array) when available."""
        from . import devicedb as _ddb
        count = None
        try:
            gw = (get_gateway(gateway) or get_state()) if gateway else get_state()
            fwb = (gw.last_summary or {}).get("firmware") or {}
            fhp = fwb.get("FHP_SN")
            count = len(fhp) if isinstance(fhp, list) else None
        except Exception:  # noqa: BLE001
            count = None
        return {"models": _ddb.apower_specs(), "apower_count": count}

    @app.get("/api/support-info")
    def api_support_info():
        """A REDACTED diagnostic bundle to paste into a GitHub issue — models, firmware,
        counts, modes and settings, with NO serials, hosts, IPs, location, or credentials.
        Timestamped; carries no user identity."""
        import time as _t
        from . import devicedb, system_setup
        settings = get_settings()
        store = None
        try:
            store = db.get_store(settings)
        except Exception:  # noqa: BLE001
            store = None

        meta = {
            "generated_at": int(_t.time()),
            "software_version": __version__,
            "build": _asset_version(),
            "platform": environment.RUNTIME,
            "install_date": (store.get_config("install_date") if store else None),
            "bridge_uptime_s": round(_t.time() - _STARTED_AT, 1),
            "updates": (store.version_history(limit=20) if store else []),
            "last_updated": (max((u.get("ts") or 0) for u in store.version_history(limit=1)) if store and store.version_history(limit=1) else None),
            "note": ("Redacted support bundle - no serials, hosts, location or credentials. "
                     "Safe to paste into a GitHub issue."),
        }

        # Gateways (redacted): model from devicedb (SyHdVersion), firmware VERSIONS only.
        gateways = []
        for i, g in enumerate(get_gateways()):
            row = {"index": i + 1, "is_mock": bool(getattr(g, "is_mock", False)),
                   "enabled": bool(getattr(g, "enabled", True))}
            if g.is_mock:
                row["model"] = "aGate (mock)"
            else:
                try:
                    fw = client.firmware(settings, host=g.active_host or g.configured_host)
                    hw = fw.get("SyHdVersion")
                    m = devicedb.gateway(hw) or {}
                    row["model"] = m.get("model") or "unknown"
                    row["vendor_model"] = m.get("vendor_model")
                    row["country"] = m.get("country")
                    row["hardware_model_id"] = hw
                    row["air_switch_amps_catalog"] = m.get("amps")   # devicedb rating (not service)
                    row["firmware"] = {k: fw.get(k) for k in
                                       ("protocolVer", "IBG_VER", "APP_VER", "AWS_VER",
                                        "DCDC_VER", "INV_VER", "BMS_VER", "METER_VER")
                                       if fw.get(k)}
                    apow = fw.get("FHP_SN") or fw.get("FPGA_VER")
                    row["apower_count"] = len(apow) if isinstance(apow, list) else None
                    row["contacted_at"] = int(_t.time())   # this read proves last contact
                except Exception:  # noqa: BLE001
                    row["model"] = "unknown (read failed)"
                _host = g.active_host or g.configured_host
                # Grid connection + import/export power-plane (1701) — service vs air-switch amps
                try:
                    prof = client.read(settings, "install_profile", host=_host) or {}
                    pp = prof.get("result") if isinstance(prof.get("result"), dict) else prof
                    gg = (lambda k: (pp.get(k) if isinstance(pp, dict) and k in pp else prof.get(k)))
                    grid = {
                        "service_amps": gg("electricSupply"),      # actual supply/main (e.g. 63A)
                        "air_switch_amps": gg("airSwitchCur"),     # aGate air-switch RATING (e.g. 100A)
                        "grid_export_enabled": bool(gg("gridExportEnable")),
                        "pcs_discharge_enabled": bool(gg("isPcsDischgEn")),
                        "import_limit_w": gg("gridSoftLimit"),     # -1 = unlimited
                        "export_limit_w": gg("gridHardLimit"),     # -1 = unlimited
                        "kw_rate_power": gg("kwRatePower"),
                    }
                    from . import battery_control as _bc
                    chg, dis = _bc.cached_ratings((_host or "").split(":")[0])
                    if chg:
                        grid["inverter_max_charge_kw"] = round(chg / 1000, 2)
                    if dis:
                        grid["inverter_max_discharge_kw"] = round(dis / 1000, 2)
                    row["grid"] = grid
                except Exception:  # noqa: BLE001
                    pass
                # Accessories: Smart Circuits (count) + Generator (if present)
                try:
                    sc = client.read(settings, "smart_circuits", host=_host) or {}
                    scp = sc.get("result") if isinstance(sc.get("result"), dict) else sc
                    if isinstance(scp, dict):
                        row["smart_circuits"] = sum(1 for i in range(1, 9) if scp.get(f"Sw{i}Name"))
                except Exception:  # noqa: BLE001
                    pass
                try:
                    gen = client.generator(settings, host=_host) or {}
                    row["generator"] = ({"installed": True,
                                         "mode": gen.get("mode_name") or gen.get("mode"),
                                         "state": gen.get("state_name")}
                                        if gen.get("installed") else {"installed": False})
                except Exception:  # noqa: BLE001
                    pass
            # Non-identifying live state from cache
            ls = getattr(g, "last_state", {}) or {}
            row["operating_mode"] = ls.get("name") or (g.cloud_mode or None)
            row["run_status"] = ls.get("run_status")
            row["soc_pct"] = ls.get("soc")
            row["cloud_vpp"] = g.cloud_vpp
            row["cloud_programme"] = bool(g.cloud_programme)   # bool only (name may identify)
            gateways.append(row)

        # System setup flags (non-PII hardware/config)
        system = {}
        try:
            host0 = _gw_host(None)
            ss = system_setup.snapshot(store, settings, None, host0) if store else {}
            system = {k.replace("system.", ""): v for k, v in ss.items()}
        except Exception:  # noqa: BLE001
            system = {}

        # Integration setup (counts + booleans; never ids/creds)
        integration = {
            "schedules": (len(store.schedules()) if store else 0),
            "ha_instances": (len(store.ha_instances()) if store else 0),
            "ha_exposed_entities": (len(store.ha_exposed_ids()) if store else 0),
            "mqtt_enabled": bool(settings.mqtt_enabled),
            "modbus_enabled": _bc_is_enabled(),
            "cloud_configured": bool(settings.fwh_cloud_email and settings.fwh_cloud_password),
            "nem_region": settings.nem_region or None,
            "dynamic_price_entity_set": bool(settings.tariff_price_entity),
            "writes_enabled": bool(settings.allow_writes),
        }

        # Billing (redacted: presence + kind only, no site/meter/utility names or addresses)
        billing = {"configured": False}
        try:
            if store:
                tariffs = store.tariffs() if hasattr(store, "tariffs") else []
                billing = {"configured": bool(tariffs), "tariff_count": len(tariffs or [])}
        except Exception:  # noqa: BLE001
            pass

        solar = {
            "pv_kwp": settings.pv_kwp, "tilt": settings.pv_tilt, "azimuth": settings.pv_azimuth,
            "forecast_configured": bool(settings.pv_latitude is not None
                                        and settings.pv_longitude is not None),
        }
        return {"meta": meta, "gateways": gateways, "solar": solar, "system_setup": system,
                "integration": integration, "billing": billing}

    @app.get("/api/disclaimer")
    def api_disclaimer(client_id: str | None = Query(None)):
        """Text + links for the first-connection legal-disclaimer modal (unofficial app).
        ``agreed`` reflects the DB record for this client_id (authoritative don't-show-again,
        survives a localStorage clear)."""
        agreed = False
        if client_id:
            try:
                st = db.get_store(get_settings())
                agreed = bool(st and st.disclaimer_agreed(client_id))
            except Exception:  # noqa: BLE001
                agreed = False
        return {
            "agreed": agreed,
            "title": "Unofficial software",
            "lines": [
                "This is an UNOFFICIAL app - NOT affiliated with, or endorsed by, FranklinWH.",
                "It talks to FranklinWH's undocumented Direct Connect (local) API and its cloud API "
                "- technically the SAME private API the official FranklinWH mobile app (and the FleetView "
                "installer portal) use, intended for those apps and not for third parties - plus the "
                "standard SunSpec Modbus TCP API (with undocumented FranklinWH extensions). Any of these "
                "may change, break, or become unavailable without notice.",
                "Provided AS-IS, without warranty of any kind. Use entirely at your own risk - "
                "the authors accept no liability for data loss, equipment damage, or service loss.",
                "Do NOT contact FranklinWH support about this app. Raise issues, defects, or "
                "feature requests on GitHub instead.",
                "Keep your system compliant with the settings your official FranklinWH app / "
                "installer configured. Using this tool to bypass safety, grid-compliance, or "
                "programme restrictions is at your own risk and is not condoned. Provided AS-IS "
                "for education/information; any use (personal or commercial) is permitted under the "
                "MIT Licence and entirely at your own risk. Please keep this notice with copies and "
                "forks (see Full terms).",
            ],
            "issues_url": DISCLAIMER_ISSUES_URL,
            "docs_url": "guide/",
            "terms_url": "https://github.com/david2069/franklinwh-direct-connect-bridge/blob/main/LICENSE",
            "version": __version__,
        }

    @app.post("/api/disclaimer/ack")
    def api_disclaimer_ack(request: Request, req: DisclaimerAckReq):
        """Record that a user AGREED to the disclaimer: persist to the DB (source of truth for
        don't-show-again) and write an agreement line to the durable log (audit trail)."""
        ip = (request.client.host if request.client else "unknown")
        cid = (req.client_id or "").strip()
        persisted = False
        if cid:
            try:
                st = db.get_store(get_settings())
                if st is not None:
                    st.record_disclaimer_ack(cid, ip=ip, version=__version__)
                    persisted = True
            except Exception:  # noqa: BLE001
                persisted = False
        # Audit line — WARNING so it stands out in the trail, like the Modbus bridge's notice.
        log.warning("User AGREED to the unofficial-app disclaimer (client=%s, ip=%s, v=%s). %s",
                    cid or "?", ip, __version__, DISCLAIMER_LINE)
        return {"ok": True, "persisted": persisted}

    @app.get("/api/logs")
    def api_logs(limit: int = Query(1000, ge=1, le=5000),
                 offset: int = Query(0, ge=0),
                 level: str | None = Query(None),
                 since: float | None = Query(None),
                 until: float | None = Query(None),
                 source: str | None = Query(None),
                 q: str | None = Query(None)):
        """Bridge log lines, NEWEST-FIRST, from the durable SQLite store (falls back to the
        in-memory ring when the store is disabled). Supports offset pagination + filters:
        ``level`` (minimum level), ``since``/``until`` (epoch-second window), ``source``
        (logger name), ``q`` (message substring). Returns ``total``/``has_more`` for the
        pager and the distinct ``sources``. Never 500s."""
        try:
            store = db.get_store(get_settings())
            if store is not None:
                min_lvl = logbuffer._LEVELS.get((level or "").strip().lower(), 0) if level else 0
                entries = store.logs(limit=limit, offset=offset, level_no_min=min_lvl,
                                     since=since, until=until, name=source, search=q)
                total = store.logs_count(level_no_min=min_lvl, since=since, until=until,
                                        name=source, search=q)
                return {"entries": entries, "total": total, "offset": offset, "limit": limit,
                        "has_more": (offset + len(entries)) < total,
                        "sources": store.log_sources()}
            # Fallback: in-memory ring (store disabled)
            return {"entries": logbuffer.get_logs(limit=limit, level=level, since=since),
                    "total": None, "offset": 0, "has_more": False, "sources": []}
        except Exception:  # noqa: BLE001
            return {"entries": [], "total": 0, "offset": 0, "has_more": False, "sources": []}

    # -- Metrics / history (local SQLite) -------------------------------------
    @app.get("/api/metrics")
    def api_metrics(
        range: str = Query("6h"),
        start: int | None = Query(None),
        end: int | None = Query(None),
        bucket: int | None = Query(None),
        points: int | None = Query(None),
        gateway: str | None = Query(None),
    ):
        """Time-series power history from the bridge's own SQLite store. Never 500s —
        returns an empty series when metrics are disabled or the DB is empty. Pass
        ``gateway`` to filter to one gateway's serial (multi-gateway)."""
        if start is not None and end is not None:
            span_key = range
        else:
            end = int(time.time())
            start = end - RANGE_SECONDS.get(range, RANGE_SECONDS["6h"])
            span_key = range
        b = _resolve_bucket(span_key, start, end, bucket, points)
        store = db.get_store(get_settings())
        if store is None:
            return {"enabled": False, "series": [], "count": 0}
        series = store.query(start, end, b, gateway=_metrics_gw_key(gateway))
        return {"enabled": True, "range": range, "start": start, "end": end,
                "bucket_s": b, "count": len(series), "series": series}

    @app.get("/api/energy/flow")
    def api_energy_flow(
        day: str | None = Query(None),
        start: float | None = Query(None),
        end: float | None = Query(None),
        gateway: str | None = Query(None),
    ):
        """Directional energy flows (the Sankey's data) for a local day or an
        explicit span. Flows are RECONSTRUCTED from the bridge's power samples by a
        merit-order split — a well-founded estimate, not a meter (the gateway reports
        node scalars, never the arcs). ``quality.coverage`` says how much of the span
        actually had samples. Never 500s."""
        _TARGET_BUCKETS, _MIN_BUCKET_S, _MAX_SPAN_DAYS = 720, 60, 366
        if start is not None and end is not None:
            if end <= start:
                raise HTTPException(400, "end must be greater than start")
            if (end - start) > _MAX_SPAN_DAYS * 86400:
                raise HTTPException(400, f"Span cannot exceed {_MAX_SPAN_DAYS} days")
            span_start, span_end, label = float(start), float(end), "custom"
        else:
            # Local-midnight day (the gateway's own totals reset at local midnight).
            try:
                d = _dt.date.fromisoformat(day) if day else _dt.date.today()
            except ValueError:
                raise HTTPException(400, f"Invalid day '{day}' — expected YYYY-MM-DD") from None
            d0 = _dt.datetime.combine(d, _dt.time.min)
            span_start = d0.timestamp()
            span_end = (d0 + _dt.timedelta(days=1)).timestamp()
            label = d.isoformat()

        now = time.time()
        query_end = min(span_end, now)
        store = db.get_store(get_settings())
        rows: list[dict] = []
        if store is not None and query_end > span_start:
            bucket = max(_MIN_BUCKET_S, int((query_end - span_start) / _TARGET_BUCKETS))
            raw = store.query(int(span_start), int(query_end), bucket, gateway=_metrics_gw_key(gateway))
            # The decomposition speaks `home_w`; our column is `load_w`.
            rows = [{**r, "home_w": r.get("load_w")} for r in raw]

        flows = _eflow.integrate(rows)
        nodes = _eflow.node_totals(flows)
        span_s = query_end - span_start
        return {
            "day": label, "start": span_start, "end": span_end, "gateway_id": gateway,
            "flows": {k: v for k, v in flows.items()
                      if k not in ("residual_kwh", "covered_s", "samples")},
            "nodes": nodes,
            "quality": {
                "coverage": round(flows["covered_s"] / span_s, 3) if span_s > 0 else 0.0,
                "covered_s": flows["covered_s"], "samples": flows["samples"],
                "residual_kwh": flows["residual_kwh"],
            },
        }

    @app.get("/api/solar/forecast")
    def api_solar_forecast(force: bool = Query(False)):
        """Weather + PV production forecast from Open-Meteo, scaled to the configured
        PV array. Needs latitude/longitude set in Settings; otherwise reports so."""
        from . import solar_forecast
        cfg = get_settings()
        if cfg.pv_latitude is None or cfg.pv_longitude is None:
            return {"configured": False,
                    "reason": "Set your location (latitude & longitude) in Settings "
                              "to enable the solar forecast."}
        fc = solar_forecast.forecast(cfg.pv_latitude, cfg.pv_longitude, kwp=cfg.pv_kwp,
                                     tilt=cfg.pv_tilt, azimuth=cfg.pv_azimuth, force=force)
        return {"configured": True, **fc,
                "pv": {"kwp": cfg.pv_kwp, "tilt": cfg.pv_tilt, "azimuth": cfg.pv_azimuth,
                       "lat": cfg.pv_latitude, "lon": cfg.pv_longitude}}

    @app.post("/api/solar/sync-location")
    def api_solar_sync_location(gateway: str | None = Query(None)):
        """Read the aGate's OWN configured location (cmd 1201 time_location) and save it
        as the solar-forecast location — no cloud needed. NB the firmware key for
        latitude is misspelled 'laitude'."""
        host = _gw_host(gateway)
        try:
            tl = client.read(get_settings(), "time_location", host=host)
        except (OSError, TransportError, TimeoutError) as e:
            raise HTTPException(status_code=502, detail=str(e))
        lat = tl.get("laitude", tl.get("latitude"))
        lon = tl.get("longitude")
        if not lat or not lon:
            raise HTTPException(status_code=422, detail="the gateway did not report a location")
        save_override("pv_latitude", float(lat)); save_override("pv_longitude", float(lon))
        cfg = get_settings(); cfg.pv_latitude = float(lat); cfg.pv_longitude = float(lon)
        return {"latitude": float(lat), "longitude": float(lon),
                "postcode": tl.get("postcode"), "timezone": tl.get("timezone")}

    @app.get("/api/metrics/info")
    def api_metrics_info():
        s = get_settings()
        store = db.get_store(s)
        out = {"enabled": metrics_active(s),
               "retention_days": s.metrics_retention_days}
        if store is not None:
            out.update(store.info())
        return out

    # ── Admin: storage insight + backup / restore / export (OPS-ADMIN-*) ──────
    import os as _os
    import re as _re

    def _backups_dir() -> str:
        d = _os.path.join(environment.DATA_DIR, "backups")
        _os.makedirs(d, exist_ok=True)
        return d

    _BACKUP_RE = _re.compile(r"^fwh-backup-\d{8}-\d{6}\.db$")

    def _safe_backup_path(name: str) -> str:
        """Resolve a backup filename to a path INSIDE the backups dir — rejects traversal."""
        if not _BACKUP_RE.match(name or ""):
            raise HTTPException(status_code=400, detail="invalid backup name")
        d = _backups_dir()
        p = _os.path.realpath(_os.path.join(d, name))
        if _os.path.dirname(p) != _os.path.realpath(d):
            raise HTTPException(status_code=400, detail="invalid backup path")
        return p

    def _human_bytes(n) -> str:
        if not isinstance(n, (int, float)):
            return "–"
        f = float(n)
        for unit in ("B", "KB", "MB", "GB"):
            if f < 1024 or unit == "GB":
                return f"{f:.0f} {unit}" if unit == "B" else f"{f:.1f} {unit}"
            f /= 1024
        return f"{f:.1f} GB"

    def _list_backups() -> list:
        d = _backups_dir()
        out = []
        for name in sorted(_os.listdir(d), reverse=True):
            if not _BACKUP_RE.match(name):
                continue
            try:
                st = _os.stat(_os.path.join(d, name))
            except OSError:
                continue
            out.append({"name": name, "bytes": st.st_size,
                        "human": _human_bytes(st.st_size), "mtime": st.st_mtime})
        return out

    @app.get("/api/admin/storage")
    def api_admin_storage():
        """DB disk-usage: total size + SQLite page accounting + per-table rows & span."""
        s = get_settings()
        store = db.get_store(s)
        if store is None:
            return {"enabled": False}
        stats = store.storage_stats()
        stats["db_human"] = _human_bytes(stats.get("db_bytes"))
        stats["retention_days"] = s.metrics_retention_days
        stats["backups"] = _list_backups()
        return stats

    @app.post("/api/admin/vacuum")
    def api_admin_vacuum():
        """Compact the DB file (reclaim freed pages)."""
        store = db.get_store(get_settings())
        if store is None:
            raise HTTPException(status_code=503, detail="metrics store is off")
        new_bytes = store.vacuum()
        _audit("db_vacuum", detail="VACUUM", result=_human_bytes(new_bytes), ok=True)
        return {"ok": True, "db_bytes": new_bytes, "db_human": _human_bytes(new_bytes)}

    @app.post("/api/admin/backup")
    def api_admin_backup_create():
        """Create a consistent DB backup; keep the newest 10, prune older."""
        store = db.get_store(get_settings())
        if store is None:
            raise HTTPException(status_code=503, detail="metrics store is off")
        stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        name = f"fwh-backup-{stamp}.db"
        path = _os.path.join(_backups_dir(), name)
        size = store.backup_to(path)
        # Retain the newest 10.
        for old in _list_backups()[10:]:
            try:
                _os.remove(_os.path.join(_backups_dir(), old["name"]))
            except OSError:
                pass
        _audit("db_backup", detail=name, result=_human_bytes(size), ok=True)
        return {"ok": True, "name": name, "bytes": size, "human": _human_bytes(size)}

    @app.get("/api/admin/backups")
    def api_admin_backups():
        return {"backups": _list_backups()}

    @app.get("/api/admin/backup/{name}")
    def api_admin_backup_download(name: str):
        path = _safe_backup_path(name)
        if not _os.path.exists(path):
            raise HTTPException(status_code=404, detail="backup not found")
        return FileResponse(path, media_type="application/octet-stream", filename=name)

    @app.delete("/api/admin/backup/{name}")
    def api_admin_backup_delete(name: str):
        path = _safe_backup_path(name)
        if _os.path.exists(path):
            _os.remove(path)
            _audit("db_backup_delete", detail=name, ok=True)
        return {"ok": True}

    @app.post("/api/admin/backup/{name}/restore")
    def api_admin_backup_restore(name: str, req: RestoreReq):
        """DESTRUCTIVE — replace the live DB with a backup. Confirm-gated (428)."""
        _guard_consequential(req.confirm, "restore a database backup")
        path = _safe_backup_path(name)
        if not _os.path.exists(path):
            raise HTTPException(status_code=404, detail="backup not found")
        store = db.get_store(get_settings())
        if store is None:
            raise HTTPException(status_code=503, detail="metrics store is off")
        try:
            store.restore_from(path)
        except Exception as e:  # noqa: BLE001
            _audit("db_restore", detail=name, result=str(e), ok=False)
            raise HTTPException(status_code=500, detail=f"restore failed: {e}")
        _audit("db_restore", detail=name, result="ok", ok=True)
        return {"ok": True, "restored": name}

    @app.get("/api/admin/metrics/export")
    def api_admin_metrics_export(fmt: str = Query("csv"), hours: int = Query(24),
                                 gateway: str | None = Query(None)):
        """Export power samples over the last ``hours`` as CSV or JSON."""
        store = db.get_store(get_settings())
        if store is None:
            raise HTTPException(status_code=503, detail="metrics store is off")
        now = int(time.time())
        start = now - max(1, min(hours, 24 * 90)) * 3600
        gw = _metrics_gw_key(gateway)
        rows = store.query(start, now, None, gateway=gw)
        cols = ["ts", "soc", "grid_w", "solar_w", "battery_w", "load_w", "generator_w", "mode"]
        stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        if fmt == "json":
            return StreamingResponse(
                iter([_json.dumps({"count": len(rows), "rows": rows})]),
                media_type="application/json",
                headers={"Content-Disposition": f"attachment; filename=fwh-metrics-{stamp}.json"})

        def _csv():
            yield ",".join(cols) + "\n"
            for r in rows:
                yield ",".join("" if r.get(c) is None else str(r.get(c)) for c in cols) + "\n"
        return StreamingResponse(
            _csv(), media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=fwh-metrics-{stamp}.csv"})

    @app.get("/api/version")
    def api_version():
        """Version + asset token, so an open tab can notice a rebuild and offer a reload.

        ``asset`` tracks the actual front-end files (see :func:`_asset_version`), not
        ``__version__`` — a rebuild during development changes the files without
        touching the version string.
        """
        return {"version": __version__, "asset": _asset_version()}

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        resp = _TEMPLATES.TemplateResponse(
            request, "index.html",
            {"version": __version__, "base_path": "", "cache_bust": _asset_version(),
             "host": get_settings().fwh_host})
        # The HTML must never be cached: it carries the hashed asset URLs, so a stale
        # page pins the browser to stale JS no matter how good the asset hashing is.
        # This is what made three consecutive fixes look absent until a hard refresh.
        resp.headers["Cache-Control"] = "no-store, must-revalidate"
        return resp

    return app
