"""Per-gateway runtime state + a small ordered registry.

Each :class:`GatewayState` holds one gateway's *active* aGate host (may change via
re-discovery), its identity (serial), last-seen firmware (OTA-change detection), and the
poller-maintained caches the REST layer serves. The registry keeps gateways in insertion
order; ``get_state()`` returns the **default** (first) gateway so all existing
single-gateway code paths keep working unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class GatewayState:
    id: str                             # stable id (opaque for DB rows; host for env seed)
    label: str = ""
    configured_host: str = ""
    active_host: str | None = None      # overrides configured_host once re-discovered
    port: int = 9000                    # per-gateway port (9000 real; ephemeral for in-proc mock)
    is_mock: bool = False               # in-process emulator gateway (Phase 2)
    publish_ha: bool = True             # publish this gateway to MQTT/HA (mocks default off)
    serial: str | None = None
    firmware: str | None = None

    # MQTT / poller runtime state (read by the REST layer for the MQTT + Settings tabs)
    mqtt_connected: bool = False        # last-known broker connection state
    node: str = ""                      # resolved device node (serial or "agate")
    last_state: dict = field(default_factory=dict)   # last published power/state dict
    state_ts: float = 0.0               # when last_state was written — the scheduler
                                        # reads this snapshot, so its AGE decides whether
                                        # a schedule may be evaluated against it at all
    last_summary: dict = field(default_factory=dict) # last-good full /api/summary (poller-cached)
    republish_requested: bool = False   # UI → poller: re-publish HA discovery
    unpublish_requested: bool = False   # UI → poller: clear entities from HA
    # FORCE truth from the Modbus M704 WSet state (the aGate 1301 run_status does NOT surface
    # a dispatch — it stays Charging/Discharging). Set by the VPP monitor loop; None until
    # first observed / when Modbus is unavailable. Read by the summary + roster for the badge.
    vpp_active: bool | None = None
    # Authoritative run-status / VPP from the Cloud API (cloud_status.poll). The local/Modbus
    # APIs can't identify a VPP — only the cloud can (effective_mode + run_status/tou_mode==9).
    # None until first cloud read; stale reads (see cloud_status.STALE_AFTER_S) are ignored.
    cloud_vpp: bool | None = None       # cloud says a VPP programme is dispatching now
    cloud_mode: str = ""                # cloud effective_mode label ("VPP Mode"/"Self-Consumption")
    cloud_programme: str | None = None  # enrolled VPP programme / partner name
    published_entities: int | None = None  # count actually published to HA via MQTT discovery
    sy_hd_version: int | None = None    # 1101 SyHdVersion -> gateway model (devicedb)
    cloud_ts: float = 0.0               # when the cloud value was last read (freshness)


# -- ordered registry (module-level; the app/poller/REST layer share one) --------
# Python dicts preserve insertion order, so a plain dict is an ordered registry.
_gateways: dict[str, GatewayState] = {}


def register_gateway(id: str, host: str, label: str | None = None, *,
                     port: int = 9000, is_mock: bool = False,
                     publish_ha: bool = True) -> GatewayState:
    """Create (or return the existing) gateway for ``id``. Idempotent — registering an
    already-known id returns the same instance so the poller/REST share one object."""
    gw = _gateways.get(id)
    if gw is None:
        gw = GatewayState(id=id, configured_host=host, active_host=host,
                          label=label or host or id, port=port, is_mock=is_mock,
                          publish_ha=publish_ha)
        _gateways[id] = gw
    return gw


def unregister_gateway(id: str) -> None:
    """Forget one gateway (roster delete)."""
    _gateways.pop(id, None)


def get_gateway(id: str) -> GatewayState | None:
    return _gateways.get(id)


def gateways() -> list[GatewayState]:
    """All registered gateways, in insertion order."""
    return list(_gateways.values())


def default_gateway() -> GatewayState | None:
    """The first-registered gateway (the single-gateway / primary), or None if empty."""
    for gw in _gateways.values():
        return gw
    return None


def get_state() -> GatewayState:
    """The default gateway's state — the single-gateway shorthand every existing code path
    uses. If the registry is still empty (e.g. tests, or before lifespan wiring), lazily
    create a default from the configured ``fwh_host`` so callers always get a usable state."""
    gw = default_gateway()
    if gw is None:
        from .config import get_settings
        s = get_settings()
        gw = register_gateway(s.fwh_host, s.fwh_host, s.fwh_host)
    return gw


def reset_gateways() -> None:
    """Test hook — forget all registered gateways."""
    _gateways.clear()
