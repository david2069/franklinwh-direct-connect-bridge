"""Bridge configuration (env / HA add-on options via pydantic-settings)."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from . import environment


class Settings(BaseSettings):
    """Runtime config. Read from env (and, in the HA add-on, from options→env).

    Env names are the field names upper-cased (e.g. ``FWH_HOST``).
    """

    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    # aGate / local API
    fwh_host: str = ""                   # single-gateway shorthand / default
    # Multi-gateway (reads/monitoring): comma-separated list, each ``host`` or ``host=Label``
    # (e.g. "10.0.0.5=Home,10.0.0.6=Shed"). Wins over fwh_host when set.
    fwh_hosts: str = ""
    fwh_port: int = 9000
    fwh_timeout: float = 20.0
    fwh_retries: int = 2
    fwh_subnet: str = ""                 # for re-discovery; blank = derive host's /24

    # bridge service
    http_host: str = "0.0.0.0"
    http_port: int = 8101
    poll_interval: int = 30
    # Smart circuits: "auto" detects from the payload (see circuits.py), or pin the
    # count — "0" none installed, "2" AU, "3" US. The firmware always returns three
    # Sw* blocks, so detection is evidence-based and always overridable.
    smart_circuit_count: str = "auto"
    log_level: str = "info"
    read_only: bool = True
    allow_writes: bool = False

    # MQTT (optional)
    mqtt_enabled: bool = False
    mqtt_host: str = "core-mosquitto"
    mqtt_port: int = 1883
    mqtt_username: str = ""
    mqtt_password: str = ""
    mqtt_prefix: str = "franklinwh-local"
    ha_discovery_prefix: str = "homeassistant"

    # Metrics / history (local SQLite). Tri-state: None = auto (see ``metrics_active``);
    # True/False = explicit override from env / add-on options.
    metrics_enabled: bool | None = None
    metrics_db: str = "/data/metrics.db"
    # 365d costs ~130 MB at a 30s poll (measured: 0.35 MB/day, ~0.67 with the tiers
    # column). Keeping a year locally removes the only reason the gateway's own
    # ~105-day history looked like the longer record.
    metrics_retention_days: int = 365

    # Home Assistant notifications (non-actionable). In the HA add-on the supervisor
    # provides SUPERVISOR_TOKEN + http://supervisor/core/api automatically; standalone can
    # set ha_url + ha_token.
    ha_notify: bool = True
    ha_url: str = ""
    ha_token: str = ""

    # Location + PV array for the Open-Meteo solar/weather forecast (FEAT-WEATHER-SOLAR).
    # lat/lon unset = feature off. Azimuth uses Open-Meteo's convention (0=S, -90=E, 90=W).
    pv_latitude: float | None = None
    pv_longitude: float | None = None
    pv_kwp: float = 5.0
    nem_region: str = ""              # AEMO NEM region for wholesale spot (NSW1/QLD1/SA1/TAS1/VIC1)
    tariff_price_entity: str = ""     # HA entity (ha:<inst>:<eid>) -> tariff.spot_price (buy, dynamic)
    tariff_feedin_entity: str = ""    # HA entity (ha:<inst>:<eid>) -> tariff.feed_in_price (sell, dynamic)
    billing_dynamic: bool = False     # price BILLING at the live wholesale rate (spot/feed-in), not the static tariff
    pv_tilt: float = 20.0
    pv_azimuth: float = 0.0

    #: How to handle a scheduled battery dispatch left in-flight by a bridge
    #: restart (none | notify | release | resume). 'notify' never touches the
    #: battery — it only alerts (honours the two-masters rule).
    dispatch_interrupt_policy: str = "notify"

    # Hybrid capability providers — fill the local hard walls (battery dispatch, cloud-only
    # writes) by delegating to an installed sibling bridge's REST API, else a library.
    # See BACKLOG HYBRID-CAPABILITIES. Phase 1 = detection only (no writes yet).
    modbus_bridge_url: str = ""       # REST base of an installed FranklinWH Modbus Bridge (dispatch)
    fwhai_url: str = ""               # REST base of an installed FWHAI (reserve / cloud-only writes)
    modbus_host: str = ""             # aGate host for the franklinwh-modbus library fallback (:502)
    fwh_cloud_email: str = ""         # franklinwh-cloud library fallback credentials
    fwh_cloud_password: str = ""
    fwh_cloud_gateway: str = ""       # cloud gateway serial (optional)


def gateway_list(settings: Settings) -> list[tuple[str, str]]:
    """The effective ``[(host, label), ...]`` gateway list.

    Precedence: parse ``fwh_hosts`` when set (each entry ``host`` or ``host=Label``);
    else fall back to the single ``fwh_host`` (label = host); else an empty list.
    """
    raw = (settings.fwh_hosts or "").strip()
    if raw:
        out: list[tuple[str, str]] = []
        for part in raw.split(","):
            part = part.strip()
            if not part:
                continue
            if "=" in part:
                host, _, label = part.partition("=")
                host, label = host.strip(), label.strip()
            else:
                host, label = part, part
            if host:
                out.append((host, label or host))
        if out:
            return out
    if settings.fwh_host:
        return [(settings.fwh_host, settings.fwh_host)]
    return []


def metrics_active(settings: Settings) -> bool:
    """Should the local SQLite metrics store be active for this runtime?

    Explicit ``metrics_enabled`` (True/False) always wins. When unset (None) we
    auto-decide: metrics are ON everywhere EXCEPT when running as an HA add-on with
    MQTT enabled — there Home Assistant's own recorder already stores history via the
    published MQTT entities, so a second local copy is redundant.
    """
    if settings.metrics_enabled is not None:
        return settings.metrics_enabled
    from .environment import IS_HA_ADDON
    return not (IS_HA_ADDON and settings.mqtt_enabled)


# -- live-editable overrides (P7) --------------------------------------------
# Only these keys can be changed at runtime via PUT /api/settings and persisted to
# a small JSON file in DATA_DIR. Everything else needs a restart (env / add-on options).
_OVERRIDE_KEYS = {"allow_writes", "log_level", "ha_notify", "ha_url", "ha_token",
                  # Cloud reserve-control credentials (HYBRID Phase 3) — live-editable so the
                  # user can enter them in Settings without a restart. Stored in overrides.json
                  # (plaintext, on the protected data volume); never returned by the API.
                  "fwh_cloud_email", "fwh_cloud_password", "fwh_cloud_gateway",
                  # Location + PV array for the solar/weather forecast (live-editable).
                  "pv_latitude", "pv_longitude", "pv_kwp", "pv_tilt", "pv_azimuth",
                  "nem_region",   # AEMO NEM wholesale spot region (live-editable)
                  "tariff_price_entity", "tariff_feedin_entity",   # HA dynamic-price provider
                  "billing_dynamic",   # price billing at the live wholesale rate
                  "dispatch_interrupt_policy"}


def overrides_path() -> Path:
    """Where runtime overrides persist — a JSON file alongside the metrics DB in DATA_DIR.
    Read at call time so tests can monkeypatch ``environment.DATA_DIR``."""
    return Path(environment.DATA_DIR) / "overrides.json"


def load_overrides() -> dict:
    """The persisted overrides as a dict. Safe: a missing/unreadable/malformed file → {}."""
    try:
        p = overrides_path()
        if not p.exists():
            return {}
        data = json.loads(p.read_text())
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001 — config load must never raise
        return {}


def apply_overrides(settings: Settings) -> None:
    """Set only the whitelisted keys from the overrides file onto ``settings``. Persisted
    overrides win over env for those keys. Unknown/restart-only keys are ignored."""
    data = load_overrides()
    for key in _OVERRIDE_KEYS:
        if key in data:
            try:
                setattr(settings, key, data[key])
            except Exception:  # noqa: BLE001 — a bad value must not break startup
                pass


def save_override_raw(key: str, value) -> None:
    """Merge ``{key: value}`` into the overrides file WITHOUT the whitelist check.

    For internal bridge state that must persist but is not a user-editable setting
    (e.g. the cloud-auth breaker), so it cannot be set through ``PUT /api/settings``
    and is not applied onto ``Settings`` by :func:`apply_overrides`. Keys are
    conventionally underscore-prefixed. Best-effort; never raises.
    """
    data = load_overrides()
    data[key] = value
    try:
        p = overrides_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2))
        tmp.replace(p)
    except Exception:  # noqa: BLE001 — persistence is best-effort
        pass


def save_override(key: str, value) -> None:
    """Merge ``{key: value}`` into the overrides file (atomic-ish). Non-whitelisted keys
    are ignored. Best-effort — a write failure never raises to the caller."""
    if key not in _OVERRIDE_KEYS:
        return
    data = load_overrides()
    data[key] = value
    try:
        p = overrides_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2))
        tmp.replace(p)
    except Exception:  # noqa: BLE001
        pass


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
        # Persisted runtime overrides win over env for the whitelisted keys.
        apply_overrides(_settings)
    return _settings
