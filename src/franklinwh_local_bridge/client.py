"""Thin adapter over the franklinwh-local-api library for the bridge's reads.

Composes the library primitives (LocalClient, discover) into the shapes the REST API
and (later) MQTT publisher need. Read-only here; keeps the library the single source of
truth for the protocol.
"""

from __future__ import annotations

import time
from typing import Any

import logging

from franklinwh_local import catalog, discover
from franklinwh_local.client import LocalClient
from franklinwh_local.transport import TransportError

from .config import Settings
from .state import get_state

log = logging.getLogger("franklinwh_local_bridge.client")


def active_host(s: Settings) -> str:
    """The IP we currently talk to — a re-discovered address wins over the configured one."""
    return get_state().active_host or s.fwh_host


def _split_hostport(h: str | None, default_port: int) -> tuple[str, int]:
    """Split an optional ``host:port`` into ``(host, port)``. A bare host keeps the
    default port. In-process mock gateways address themselves as ``127.0.0.1:<ephemeral>``
    so the whole gateway plumbing (which only threads a host string) still reaches them —
    the split happens here rather than adding a port to every read signature. IPv6 (more
    than one colon) is left alone."""
    if h and h.count(":") == 1:
        host, _, port = h.rpartition(":")
        if port.isdigit():
            return host, int(port)
    return (h or ""), default_port


def _client(s: Settings, host: str | None = None) -> LocalClient:
    h, port = _split_hostport(host or active_host(s), s.fwh_port)
    return LocalClient(h, port, timeout=s.fwh_timeout, retries=s.fwh_retries)


# Every one-call LocalClient read method the bridge exposes 1:1 at /api/cmd/<name>.
# NOTE: grid_profile fans out ~25 cmdTypes (SLOW) and wifi_scan is slow — these are
# on-demand only; never auto-poll them.

#: Reads not backed by a catalog entry, so they must be named explicitly.
_EXTRA_READS = frozenset({
    "firmware",      # from the 1101 login manifest, not its own cmdType
    "grid_profile",  # convenience fan-out over ~25 grid-compliance cmdTypes (SLOW)
})

#: Catalog entries that are NOT exposed as an on-demand read endpoint.
_EXCLUDED_READS = frozenset({
    "login",         # the handshake; performed implicitly by every read
})


def _read_methods() -> set[str]:
    """Read endpoints, DERIVED from the library catalog.

    Every catalog entry that ``LocalClient`` implements as a callable is exposed
    as ``/api/cmd/<name>``. Deriving rather than listing keeps this in step with
    the library automatically — the hand-maintained version had fallen 7 methods
    behind (battery_cells, power_electronics, device_firmware, device_states,
    device_check, agate_serial, energy_history), which is the same drift the
    library itself hit and fixed the same way.

    Methods taking only defaulted arguments (``battery_cells(dev_id=1)``,
    ``energy_history(date=None)``) are callable with no arguments, which is how
    :func:`read` invokes them.
    """
    names = {i.name for i in catalog.CATALOG.values()
             if callable(getattr(LocalClient, i.name, None))}
    return (names - _EXCLUDED_READS) | _EXTRA_READS


READ_METHODS = _read_methods()


def read(s: Settings, name: str, host: str | None = None) -> Any:
    """Run one LocalClient read method by name within a single login session.

    ``name`` must be in :data:`READ_METHODS` (raises ValueError otherwise). This is the
    generic backing for the /api/cmd/<name> surface — a fair 1:1 with the library.
    ``host`` selects the gateway (multi-gateway); None → the default gateway.
    """
    if name not in READ_METHODS:
        raise ValueError(f"unknown read '{name}'")
    return read_with_request(s, name, host=host)[0]


def read_with_request(s: Settings, name: str,
                      host: str | None = None) -> tuple[Any, dict | None]:
    """Like :func:`read`, but also returns the frame that was ACTUALLY sent.

    The bridge shows that frame beside every reading so a reader can verify the
    request rather than trust a reconstruction of it — which matters because the
    read payload is NOT uniform: 1725 reads with ``opt:1``, several commands need
    an ``id``, and 1303 needs a date.
    """
    if name not in READ_METHODS:
        raise ValueError(f"unknown read '{name}'")
    with _client(s, host) as c:
        c.login()
        payload = getattr(c, name)()
    return payload, getattr(c.transport, "last_request", None)


def call(s: Settings, cmd: int, data_area: dict | None = None,
         host: str | None = None) -> dict[str, Any]:
    """Generic passthrough — issue any request cmdType and return its response dataArea."""
    with _client(s, host) as c:
        c.login()
        return c.call(cmd, data_area)


def set_der_comms(s: Settings, sunspec_modbus: bool | None = None,
                  ieee2030_5: bool | None = None,
                  host: str | None = None) -> dict[str, Any]:
    """Write DER comms toggles (1205 opt:1, full-block RMW). Delayed-apply — the reply is
    NOT proof; verify at the interface level (:502 / status2030_5). ``ieee2030_5`` maps to
    the library's SEP2 ``enable`` field."""
    with _client(s, host) as c:
        c.login()
        return c.set_der_comms(sunspec_modbus=sunspec_modbus, sep2=ieee2030_5)


def reboot(s: Settings, host: str | None = None) -> dict[str, Any]:
    """DESTRUCTIVE — reboot the aGate (1721 opt:1). Drops the connection while it restarts
    and may trigger 4G failover; a dropped socket is expected and returns dropped=True."""
    with _client(s, host) as c:
        c.login()
        return c.reboot()


def rediscover(s: Settings, host: str | None = None,
               serial: str | None = None) -> str | None:
    """Scan the subnet for the aGate (it can move IP on reboot / DHCP). Prefer the host
    whose serial matches the one we've seen. Returns the new host (or None); the caller
    adopts it. Back-compat: a single-arg call (host=None) still updates the default
    gateway's ``active_host`` so existing behaviour/tests are preserved."""
    target = host or active_host(s)
    known_serial = serial if serial is not None else get_state().serial
    subnet = s.fwh_subnet or (target.rsplit(".", 1)[0] + ".0/24")
    try:
        targets = discover.expand_targets(subnet)
    except ValueError:
        return None
    log.info("re-discovering aGate on %s ...", subnet)
    results = discover.scan(targets, timeout=1.0, probe=True)
    hits = [r for r in results if getattr(r, "sendmqtt_confirmed", False)]
    chosen = None
    if known_serial:
        chosen = next((r.host for r in hits
                       if (r.manifest or {}).get("IBG_SN") == known_serial), None)
    if not chosen and hits:
        chosen = hits[0].host
    if chosen and chosen != target:
        log.warning("aGate moved: %s → %s", target, chosen)
        if host is None:            # back-compat: single-arg adopts on the default gateway
            get_state().active_host = chosen
    return chosen


def health(s: Settings, host: str | None = None) -> dict[str, Any]:
    """Interface-level health: ping (informational) + a real sendMqtt round-trip with
    latency + :502 (Modbus) + der_comms config. Mirrors the CLI ``health`` command."""
    host = host or active_host(s)
    out: dict[str, Any] = {
        "host": host,
        "ping": discover.ping(host, timeout=1.0),
        "sendmqtt_9000": False,
        "latency_ms": None,
        "modbus_502": any(discover.port_open(host, 502, timeout=3.0) for _ in range(3)),
        "sunsMdEn": None,
    }
    try:
        with _client(s, host) as c:
            t0 = time.time()
            c.login()
            out["latency_ms"] = round((time.time() - t0) * 1000, 1)
            out["sendmqtt_9000"] = True
            try:
                out["sunsMdEn"] = c.der_comms().get("sunsMdEn")
            except (OSError, TransportError, TimeoutError):
                pass
    except (OSError, TransportError, TimeoutError) as e:
        out["error"] = str(e)
    out["ok"] = out["sendmqtt_9000"]
    return out


def network_bundle(s: Settings, host: str | None = None) -> dict[str, Any]:
    """All local network diagnostics in ONE aGate session: reachability (ping/:9000/:502 +
    login latency), connectivity (1113 router/net/aws), interfaces (1118), interface switches
    (1119), and the AWS-IoT cloud config (1121). Each block is best-effort — a failed sub-read
    is left None so a partial view still returns. Credentials are redacted by the caller."""
    host = host or active_host(s)
    reach: dict[str, Any] = {
        "host": host,
        "ping": discover.ping(host, timeout=1.0),
        "sendmqtt_9000": False,
        "latency_ms": None,
        "modbus_502": any(discover.port_open(host, 502, timeout=3.0) for _ in range(3)),
    }
    out: dict[str, Any] = {"host": host, "reachability": reach,
                           "connectivity": None, "interfaces_raw": None,
                           "switches": None, "cloud": None}
    try:
        with _client(s, host) as c:
            t0 = time.time()
            c.login()
            reach["latency_ms"] = round((time.time() - t0) * 1000, 1)
            reach["sendmqtt_9000"] = True
            for key, fn in (("connectivity", c.connectivity),
                            ("interfaces_raw", c.network_interfaces),
                            ("switches", c.network_switches),
                            ("cloud", c.cloud_config)):
                try:
                    out[key] = fn()
                except (OSError, TransportError, TimeoutError):
                    pass
    except (OSError, TransportError, TimeoutError) as e:
        out["error"] = str(e)
    reach["ok"] = reach["sendmqtt_9000"]
    return out


def power(s: Settings, host: str | None = None) -> dict[str, Any]:
    with _client(s, host) as c:
        c.login()
        return c.power_flow()


def der_comms(s: Settings, host: str | None = None) -> dict[str, Any]:
    with _client(s, host) as c:
        c.login()
        return c.der_comms()


def cloud_stats(s: Settings, host: str | None = None) -> dict[str, Any]:
    """Read power_flow + smart_circuits in ONE aGate session and translate to the
    franklinwh-cloud ``Stats`` shape (see :mod:`cloud_compat`). One login round-trip
    on the flaky local link instead of two. Smart-circuit switch states are best-effort
    — a failed 1409 read still yields valid stats (switch_*_state stay at default)."""
    from . import cloud_compat
    with _client(s, host) as c:
        c.login()
        pf = c.power_flow()
        try:
            sw = c.smart_circuits()
        except (OSError, TransportError, TimeoutError):
            sw = None
    return cloud_compat.stats_from_power_flow(pf, sw_payload=sw)


def cloud_reserves(s: Settings, host: str | None = None) -> list[dict[str, Any]]:
    """Read mode_list + mode_soc in ONE aGate session and translate to the
    franklinwh-cloud ``get_all_mode_soc`` shape (list of per-mode reserve dicts; see
    :mod:`cloud_compat`). One login round-trip instead of two. mode_soc is best-effort
    — a failed 1406 read still yields reserves (min/maxSoc fall back to 0/100)."""
    from . import cloud_compat
    with _client(s, host) as c:
        c.login()
        ml = c.mode_list()
        try:
            soc = c.mode_soc()
        except (OSError, TransportError, TimeoutError):
            soc = None
    return cloud_compat.reserves_from_mode_list(ml, soc)


def cloud_tou(s: Settings, host: str | None = None) -> dict[str, Any]:
    """Read mode_list + tou_schedule in ONE aGate session and translate to the
    franklinwh-cloud ``get_gateway_tou_list`` envelope ({code, message, result}; see
    :mod:`cloud_compat`). mode_list (1726) is the primary source for result.currendId +
    result.list; tou_schedule (1408) is best-effort enrichment — a failed 1408 read
    still yields the mode list."""
    from . import cloud_compat
    with _client(s, host) as c:
        c.login()
        ml = c.mode_list()
        try:
            ts = c.tou_schedule()
        except (OSError, TransportError, TimeoutError):
            ts = None
    return cloud_compat.tou_from_mode_list(ml, ts)


def cloud_mode(s: Settings, requested_workmode: int | None = None,
               host: str | None = None) -> dict[str, Any]:
    """Read power_flow + mode_list (+ mode_soc, and tou_schedule only for TOU) in ONE
    aGate session and translate to the franklinwh-cloud ``get_mode`` flat dict. Returns
    the active mode when ``requested_workmode`` is None."""
    from . import cloud_compat
    with _client(s, host) as c:
        c.login()
        pf = c.power_flow()
        ml = c.mode_list()
        try:
            ms = c.mode_soc()
        except (OSError, TransportError, TimeoutError):
            ms = None
        # Only TOU needs the schedule detail; determine the target's workMode first.
        target_wm = requested_workmode
        if target_wm is None:
            cur = ml.get("current_id")
            entry = next((e for e in ml.get("list", []) or [] if e.get("id") == cur), None)
            target_wm = entry.get("scheduling_type") if entry else None
        ts = None
        if target_wm == 1:
            try:
                ts = c.tou_schedule()
            except (OSError, TransportError, TimeoutError):
                ts = None
    return cloud_compat.mode_from_reads(pf, ml, ms, ts, requested_workmode)


def firmware(s: Settings, host: str | None = None) -> dict[str, Any]:
    with _client(s, host) as c:
        return c.firmware()


def writes_enabled(s: Settings) -> bool:
    """Global write-gate dropped (FEAT-WRITE-CONFIRM): reversible writes just work.
    The genuinely consequential actions (operating-mode change, off-grid) are guarded
    at the endpoint by an explicit ``confirm`` (HTTP 428) instead — see app._guard_consequential.
    The legacy ``allow_writes`` setting is retained for back-compat but no longer blocks."""
    return True


def set_mode(s: Settings, mode: str, host: str | None = None) -> dict[str, Any]:
    """Switch operating mode (1727) — accepts id / full name / alias (tou/self/backup),
    the same convention as the CLI and franklinwh-cloud. Verified by the current_id change."""
    with _client(s, host) as c:
        c.login()
        before = c.mode_list().get("current_id")
        reply = c.set_mode(mode)                        # LocalClient.set_mode
        after = c.mode_list().get("current_id")
        return {"ok": reply.get("result") == 0, "result": reply.get("result"),
                "current_id_before": before, "current_id_after": after}


def set_offgrid(s: Settings, on: bool, soc: int = 5,
                host: str | None = None) -> dict[str, Any]:
    """Go off-grid / reconnect (1723)."""
    with _client(s, host) as c:
        c.login()
        reply = c.set_offgrid(on, soc)
        return {"ok": reply.get("result") == 0, "result": reply.get("result")}


class NotInstalledError(RuntimeError):
    """Raised when a write targets hardware the gateway does not report."""


def circuits(s: Settings, host: str | None = None,
             override: str = "auto") -> dict[str, Any]:
    """Smart-circuit config (1409) + metering (1411) in ONE aGate session.

    Metering is best-effort: a failed 1411 still yields the config, with electricals
    reported as ``None`` rather than a misleading zero.
    """
    from . import circuits as _circuits, devicedb
    with _client(s, host) as c:
        manifest = c.login()          # SyHdVersion rides along free with every login
        cfg = c.smart_circuits()
        try:
            mtr = c.smart_circuit_meter()
        except (OSError, TransportError, TimeoutError):
            mtr = None
    model = devicedb.describe(manifest)
    view = _circuits.build(cfg, mtr, override=override,
                           expected=model.get("expected_circuits"))
    view["gateway"] = model
    return view


def set_circuit_schedule(s: Settings, circuit: int, windows: list[dict],
                         today: str, host: str | None = None) -> dict[str, Any]:
    """Attempt a smart-circuit schedule write — delegates to the library.

    The protocol recipe and its hardware findings live in
    ``franklinwh_local.client.set_circuit_schedule``; this only turns the bridge's
    two-window editor shape into the firmware's four slots.

    **The aGate discards these on FW V12R02B30D06** (live-tested 2026-09-14, five
    payload shapes, control ruled out the transport). ``discarded`` flags the
    accepted-but-ignored case so ``result: 0`` cannot read as success.
    """
    from . import circuits as _circuits
    if circuit not in range(1, _circuits.MAX_CIRCUITS + 1):
        raise ValueError(f"circuit must be 1..{_circuits.MAX_CIRCUITS}")

    with _client(s, host) as c:
        c.login()
        patch = _circuits.build_schedule_write(c.smart_circuits(), circuit,
                                               windows, today)
        out = c.set_circuit_schedule(circuit, patch[f"Sw{circuit}Time"],
                                     patch[f"Sw{circuit}TimeEn"])
    out["hardware_verified"] = False
    out["hardware_note"] = out.pop(
        "note", "schedule writes are discarded on the observed firmware")
    return out


def set_generator_enabled(s: Settings, on: bool,
                          host: str | None = None) -> dict[str, Any]:
    """Turn the generator feature on/off (1901 ``genEn``), read-back verified."""
    with _client(s, host) as c:
        c.login()
        return c.set_generator(genEn=1 if on else 0)


def set_generator_window(s: Settings, window: int, enabled: bool,
                         start: str | None = None, end: str | None = None,
                         host: str | None = None) -> dict[str, Any]:
    """Set one generator operating window (1901). Hardware-verified 2026-09-14."""
    with _client(s, host) as c:
        c.login()
        return c.set_generator_window(window, enabled, start, end)


def set_generator_exercise(s: Settings, host: str | None = None,
                           **changes: Any) -> dict[str, Any]:
    """Set the generator maintenance/exercise run (1901)."""
    with _client(s, host) as c:
        c.login()
        return c.set_generator_exercise(**changes)


def set_generator_soc(s: Settings, start_below: int, stop_above: int,
                      host: str | None = None) -> dict[str, Any]:
    """Set generator auto start/stop SoC thresholds (1901)."""
    with _client(s, host) as c:
        c.login()
        return c.set_generator_soc(start_below, stop_above)


#: cmdTypes whose WRITE half is destructive or hard to undo. Not blocked — this is a
#: diagnostic console for the gateway's owner — but the caller is told, so "send" is
#: never an accident. Read (``opt:0``) on any of these is harmless.
DANGEROUS_WRITES: dict[int, str] = {
    1721: "device_control — reboot / reset / update. 'reset' is almost certainly a "
          "factory reset and has never been tested.",
    1501: "firmware_deliver — writing pushes a firmware file.",
    1503: "firmware_upgrade — writing triggers an OTA upgrade.",
    1723: "offgrid — islands the house (or reconnects it).",
    1727: "mode_page — opt:3 SWITCHES THE ACTIVE OPERATING MODE.",
    1111: "wifi_config — can move the gateway onto a different network, or off it.",
    1205: "der_comms — SunSpec Modbus / IEEE 2030.5 toggles; hands dispatch to a DERMS.",
    1701: "install_profile grid power-plane — gridSoftLimit/gridHardLimit/gridExportEnable/"
          "isPcsDischgEn. UNVERIFIED local write: may be silently ignored, OR may stop grid "
          "export/discharge. Full-block RMW + read-back verify; test booleans last.",
}


def raw_command(s: Settings, cmd: int, data: dict | None = None,
                host: str | None = None) -> dict[str, Any]:
    """Send ONE arbitrary cmdType and return the request and raw response verbatim.

    The point is fidelity, not convenience: the ``dataArea`` sent and the reply received
    are returned exactly as they went over the wire, with nothing normalised, scaled or
    renamed. That is what makes it usable for protocol work — a decoded view hides
    precisely the detail you are looking for.

    Read-only by default: anything other than ``opt:0`` is a write and is gated by the
    caller. See :data:`DANGEROUS_WRITES` for the codes worth a second look.
    """
    from franklinwh_local import catalog
    import time as _time

    # `data or default` is WRONG here: {} is falsy, so an explicitly empty dataArea
    # silently became the command's read payload — choosing "no opt" in the console
    # actually sent {"opt":1} for 1725. Only a MISSING dataArea may take the default.
    payload = dict(catalog.read_payload(int(cmd)) if data is None else data)
    info = catalog.CATALOG.get(int(cmd))
    is_write = payload.get("opt") != catalog.read_payload(int(cmd)).get("opt")
    t0 = _time.monotonic()
    with _client(s, host) as c:
        c.login()
        reply = c.call(int(cmd), payload)
    elapsed = round((_time.monotonic() - t0) * 1000)

    return {
        "request": {"cmdType": int(cmd), "dataArea": payload},
        "response": reply,
        "elapsed_ms": elapsed,
        "catalog": ({"name": info.name, "description": info.description,
                     "response_cmd": info.response}
                    if info else None),
        # result != 0 means the gateway REFUSED the frame. result == 0 means it parsed
        # it — NOT that a setting was applied; several commands accept and discard.
        "accepted": reply.get("result") == 0,
        # Read vs write is per COMMAND, not "opt == 0": 1725 reads with opt:1.
        "is_write": is_write,
        "warning": DANGEROUS_WRITES.get(int(cmd)) if is_write else None,
    }


def firmware_all(s: Settings, host: str | None = None) -> dict[str, Any]:
    """Gateway firmware (1101 manifest) plus PER-DEVICE firmware (1833), in one session.

    The manifest alone is gateway-level. Several of its fields are arrays with one
    entry per aPower (``FHP_SN``, ``BMS_VER``, ``INV_VER`` …) but nothing labels which
    battery each entry belongs to, and it omits ``ibg_iot`` / ``ibg_local`` / ``pe_ver``
    entirely. 1833 fills both gaps, keyed by device id.
    """
    from franklinwh_local import catalog
    out: dict[str, Any] = {"gateway": {}, "devices": []}
    with _client(s, host) as c:
        manifest = c.login()
        out["gateway"] = {k: manifest.get(k) for k in c.FIRMWARE_FIELDS
                          if k in manifest}
        try:
            modules = c.battery_modules()
            ids = [d.get("id") for d in (modules.get("devMap") or []) if d.get("id")]
        except (OSError, TransportError, TimeoutError):
            ids = [1]
        for dev_id in ids or [1]:
            try:
                out["devices"].append(c.device_firmware(dev_id))
            except (OSError, TransportError, TimeoutError) as e:
                out["devices"].append({"id": dev_id, "error": str(e)})
    return out


def device_model(s: Settings, host: str | None = None) -> dict[str, Any]:
    """Identify the gateway from the 1101 login manifest (``SyHdVersion``)."""
    from . import devicedb
    with _client(s, host) as c:
        return devicedb.describe(c.login())


def solar(s: Settings, host: str | None = None) -> dict[str, Any]:
    """Solar config (1903) + live flow (1301) in ONE aGate session.

    Live flow is best-effort: a failed 1301 still yields the config, with live
    power reported as ``None`` rather than a misleading zero.
    """
    from . import solar as _solar
    with _client(s, host) as c:
        c.login()
        cfg = c.solar_pv()
        try:
            flow = c.power_flow()
        except (OSError, TransportError, TimeoutError):
            flow = None
        try:
            run = c.ibg_run_status()      # 1707 carries the per-relay states
        except (OSError, TransportError, TimeoutError):
            run = None
    return _solar.build(cfg, flow, run)


def generator(s: Settings, host: str | None = None) -> dict[str, Any]:
    """Generator config + state (1901) in ONE aGate session."""
    from . import generator as _gen
    with _client(s, host) as c:
        c.login()
        return _gen.build(c.generator())


def set_generator_mode(s: Settings, mode: str,
                       host: str | None = None) -> dict[str, Any]:
    """Set the generator operating mode — 1901 full-block read-modify-write.

    Same shape as the proven 1409 write: read the block, change one field, echo
    everything else back, then re-read to verify. Echoing the whole block matters
    here because 1901 also carries the charge windows — a partial write would risk
    clearing them.

    Refuses when no generator is detected: this write has never been exercised
    against generator hardware, so it must not be fired blind at a system that has
    none. See BACKLOG FEAT-GENERATOR.
    """
    from . import generator as _gen
    want = _gen.MODE_TO_VALUE.get(mode)
    if want is None:
        raise ValueError(f"mode must be one of {sorted(_gen.MODE_TO_VALUE)}")

    with _client(s, host) as c:
        c.login()
        before = c.generator()
        if not _gen.installed(before):
            raise NotInstalledError("no generator detected — refusing to write generator mode")
        block = {k: v for k, v in before.items()
                 if k not in ("opt", "result", "reason")}
        block.update({"opt": 1, "manuSw": want})
        reply = c.call(1901, block)
        after = c.generator()

    return {
        "ok": reply.get("result") == 0 and after.get("manuSw") == want,
        "result": reply.get("result"),
        "before": before.get("manuSw"),
        "after": after.get("manuSw"),
        "confirmed": after.get("manuSw") == want,
        "hardware_verified": False,
        "hardware_note": ("1901 mode write has NOT been exercised on generator "
                          "hardware; the read-back is the only safety net."),
    }


def set_smart_circuit(s: Settings, circuit: int, on: bool,
                      host: str | None = None) -> dict[str, Any]:
    """Turn a smart circuit on/off (1409 full-block RMW) in ONE aGate session. Returns the
    library's read-back-verified dict ({ok, result, before, after, confirmed, ...}); ``ok``
    is True only when the re-read confirms. NOT yet hardware-verified — the read-back is the
    safety net."""
    with _client(s, host) as c:
        c.login()
        return c.set_smart_circuit(circuit, on)


#: The 1701 install_profile fields that make up the grid import/export power plane.
#: -1 = unlimited (kwRatePower/gridSoftLimit/gridHardLimit); the two *Enable fields are 0/1.
GRID_LIMIT_WRITABLE = frozenset(
    {"kwRatePower", "gridSoftLimit", "gridHardLimit", "gridExportEnable", "isPcsDischgEn"})


def set_grid_limits(s: Settings, changes: dict[str, Any], host: str | None = None,
                    dry_run: bool = False) -> dict[str, Any]:
    """Write the 1701 grid power-plane limits by full-block read-modify-write, in ONE aGate
    session, with a self-verifying read-back.

    **This is an UNVERIFIED write path.** No one has proven the aGate applies a local 1701
    write — on this firmware a command can be ACKed (``result:0``) and silently ignored (as
    reserved SoC is). The re-read is the ONLY safety net: ``ok`` is True only when every
    changed field reads back as asked. ``gridExportEnable``/``isPcsDischgEn`` can stop grid
    export/discharge entirely, so the caller gates this behind an explicit confirm and the
    UI tests those booleans last.

    ``dry_run`` reads the block and returns the EXACT frame that WOULD be sent, without
    sending. Returns ``{ok, result, reason, requested, before, after, confirmed, mismatched,
    frame}`` (or ``{dry_run, frame, before, requested}``).
    """
    unknown = set(changes) - GRID_LIMIT_WRITABLE
    if unknown:
        raise ValueError(f"not writable on 1701 grid plane: {sorted(unknown)}")
    if not changes:
        raise ValueError("no grid-limit fields to change")
    with _client(s, host) as c:
        c.login()
        prior = c.install_profile()
        block = {k: v for k, v in prior.items() if k not in ("opt", "result", "reason")}
        before = {k: prior.get(k) for k in changes}
        block.update(changes)
        block["opt"] = 1
        frame = {"cmdType": int(1701), "dataArea": block}
        if dry_run:
            return {"dry_run": True, "frame": frame, "before": before,
                    "requested": dict(changes)}
        reply = c.call(1701, block)
        post = c.install_profile()
        after = {k: post.get(k) for k in changes}
        mismatched = {k: {"requested": v, "actual": after.get(k)}
                      for k, v in changes.items() if after.get(k) != v}
        return {
            "ok": bool(reply.get("result") in (0, None) and not mismatched),
            "result": reply.get("result"),
            "reason": reply.get("reason"),
            "requested": dict(changes),
            "before": before,
            "after": after,
            "confirmed": not mismatched,
            "mismatched": mismatched,
            "frame": frame,
        }


def battery(s: Settings, host: str | None = None, dev_id: int = 1) -> dict[str, Any]:
    """Full BMS view in ONE aGate session: per-cell telemetry + electrical + states.

    Combines 1705 (cells), 1703 (grid/DC bus), 1835 (states), 1833 (serials/firmware)
    and 1105 (unit list). Hitting the four /api/cmd/* endpoints separately would open
    four sessions against a device that is slow and on flaky wifi; this opens one.

    Each block is best-effort — a failed sub-read yields ``None`` for that block with
    the reason recorded, rather than failing the whole view. Partial telemetry beats
    none when the link is marginal.
    """
    out: dict[str, Any] = {"id": dev_id, "ok": False, "error": None}
    blocks = {}
    try:
        with _client(s, host or active_host(s)) as c:
            c.login()
            for key, fn in (("cells", lambda: c.battery_cells(dev_id)),
                            ("electrical", lambda: c.power_electronics(dev_id)),
                            ("states", lambda: c.device_states(dev_id)),
                            ("firmware", lambda: c.device_firmware(dev_id)),
                            ("units", c.device_check)):
                try:
                    blocks[key] = fn()
                except Exception as e:  # noqa: BLE001 — partial view beats none
                    blocks[key] = None
                    blocks.setdefault("errors", {})[key] = str(e)
            st = blocks.get("states") or {}
            if st:
                # Decode the state codes rather than showing bare integers — the
                # enums match franklinwh_cloud.const.states exactly.
                from franklinwh_local import catalog as _cat
                st["bmsState_desc"] = _cat.bms_state_desc(st.get("bmsState"))
                st["peState_desc"] = _cat.pcs_state_desc(st.get("peState"))
            # DCDCStatus (from 1703 electrical) is the charge-state field. Live-verified
            # on this firmware against bmsState + current direction: 4=Standby, 6=Charging,
            # 7=Discharging — matches franklinwh_cloud.const.DCDC_STATE. runMode /
            # inverterStatus stay RAW: they held steady at 8 through standby/charge/
            # discharge, so they are NOT charge states and their domain is unproven.
            el = blocks.get("electrical") or {}
            if el and el.get("DCDCStatus") is not None:
                from franklinwh_local import catalog as _cat2
                el["DCDCStatus_desc"] = _cat2.DCDC_STATE.get(el.get("DCDCStatus"))
        out["ok"] = blocks.get("cells") is not None
    except (TransportError, OSError, TimeoutError, ValueError) as e:
        out["error"] = str(e)
    out.update(blocks)
    return out


def _tou_tiers_from_power_flow(pf: dict) -> dict:
    """The 1301 tariff-tier accumulator arrays, if present.

    Running daily totals (they reset at midnight) for sharp/peak/flat/valley.
    Whichever grew between two samples is the tier the device treated as active,
    which is the only way to observe when the tariff boundary moves — the gateway
    keeps only end-of-day totals, so unrecorded days cannot be recovered.
    """
    return {k: pf[k] for k in ("sharp", "peak", "flat", "valley")
            if isinstance(pf.get(k), list)}


def _battery_from_power_flow(pf: dict[str, Any] | None) -> dict[str, Any]:
    """Extract a battery summary block from a single ``power_flow`` (1301) payload — SoC,
    run status (+ label), ambient temp, module count and per-module rows. Pure + None-safe:
    missing/empty per-module arrays (``fhpSn``/``fhpSoc``/``fhpPower``) yield an empty
    ``modules`` list, never an error. NO device round-trip — the caller already has ``pf``."""
    pf = pf or {}
    sns = pf.get("fhpSn") or []
    socs = pf.get("fhpSoc") or []
    powers = pf.get("fhpPower") or []
    modules = []
    for i, sn in enumerate(sns):
        modules.append({
            "sn": sn,
            "soc": socs[i] if i < len(socs) else None,
            "power_kw": powers[i] if i < len(powers) else None,
        })
    count = pf.get("devNum") or len(sns) or None
    rs = pf.get("run_status")
    return {
        "soc": pf.get("soc"),
        "run_status": rs,
        "run_status_desc": catalog.run_status_desc(rs) if rs is not None else None,
        "t_amb": pf.get("t_amb"),
        "count": count,
        "modules": modules,
    }


def _energy_today_from_power_flow(pf: dict[str, Any] | None) -> dict[str, Any]:
    """Extract today's kWh totals from a single ``power_flow`` (1301) payload. Pure,
    None-safe, rounded to 2 dp. Missing keys → None (the emulator omits these)."""
    pf = pf or {}

    def _kwh(key: str) -> float | None:
        v = pf.get(key)
        return round(v, 2) if isinstance(v, (int, float)) else None

    return {
        "solar": _kwh("kwh_sun"),
        "grid_in": _kwh("kwh_uti_in"),
        "grid_out": _kwh("kwh_uti_out"),
        "charged": _kwh("kwh_fhp_chg"),
        "discharged": _kwh("kwh_fhp_di"),
        "home": _kwh("kwh_load"),
        "generator": _kwh("kwh_gen"),
    }


def summary(s: Settings, host: str | None = None) -> dict[str, Any]:
    """Everything the dashboard needs in ONE aGate session (one login) — efficient on the
    flaky local link vs. five separate connect/login round-trips. Reads ``host`` when given
    (multi-gateway); the caller (poller) stores serial/firmware/caches on its gateway — this
    function no longer mutates global state."""
    host = host or active_host(s)
    out: dict[str, Any] = {
        "host": host, "ok": False, "latency_ms": None,
        "configured_host": s.fwh_host, "rediscovered": host != s.fwh_host,
        "mqtt_enabled": s.mqtt_enabled, "read_only": s.read_only,
        "writes_enabled": writes_enabled(s),
    }
    _ph, _pp = _split_hostport(host, s.fwh_port)
    out["ping"] = discover.ping(_ph, timeout=1.0)
    out["modbus_502"] = any(discover.port_open(_ph, 502, timeout=3.0) for _ in range(3))
    try:
        with _client(s, host) as c:
            t0 = time.time()
            manifest = c.login()
            out["latency_ms"] = round((time.time() - t0) * 1000, 1)
            out["ok"] = True
            pf = c.power_flow()
            out["power"] = {
                "soc": pf.get("soc"), "grid_w": pf.get("p_uti"), "solar_w": pf.get("p_sun"),
                "battery_w": pf.get("p_fhp"), "load_w": pf.get("p_load"),
                # Daily kWh counters (aGate resets at local midnight) — actual-vs-forecast + flow split
                "kwh_sun": pf.get("kwh_sun"), "kwh_load": pf.get("kwh_load"),
                "kwh_uti_in": pf.get("kwh_uti_in"), "kwh_uti_out": pf.get("kwh_uti_out"),
                "kwh_fhp_chg": pf.get("kwh_fhp_chg"), "kwh_fhp_di": pf.get("kwh_fhp_di"),
                "kwh_gen": pf.get("kwh_gen"),
                # Raw 1301 name — for TOU this is the site's TARIFF, not a mode
                # name. Overwritten with the canonical label below once mode_list
                # resolves the active id; see _canonical_power_mode.
                "generator_w": pf.get("p_gen"), "mode": pf.get("name"),
                "run_status": pf.get("run_status"),
                "run_status_desc": (catalog.run_status_desc(pf.get("run_status"))
                                    if pf.get("run_status") is not None else None),
                # Islanded (5/6/7) and VPP/force (9) — surfaced prominently in the top nav.
                "off_grid": pf.get("run_status") in (5, 6, 7),
                "vpp": pf.get("run_status") == 9,
            }
            # Richer, dashboard-parity blocks from the SAME power_flow read (no extra
            # device round-trip). power stays unchanged for back-compat.
            out["battery"] = _battery_from_power_flow(pf)
            out["energy_today"] = _energy_today_from_power_flow(pf)
            # Tariff-tier accumulators, from the SAME read. Kept out of "power"
            # (and therefore out of the MQTT state payload) — they exist to be
            # persisted for later analysis, not published every poll.
            out["tou_tiers"] = _tou_tiers_from_power_flow(pf)
            ml = c.mode_list()
            cur = ml.get("current_id")
            modes = []
            for m in ml.get("list", []):
                label = catalog.mode_label(m)          # canonical, e.g. "Time-of-Use"
                raw = m.get("name", "")                # site tariff, e.g. "Ausgrid EA11 TOU"
                modes.append({
                    "name": label,
                    "tariff": raw if raw and raw != label else None,
                    "reserved_soc": m.get("reserved_soc"),
                    "workmode": m.get("scheduling_type"),
                    "active": m.get("id") == cur,
                })
            out["mode"] = {"current_id": cur, "modes": modes}
            # canonical name of the active mode for the power card
            active = next((m for m in modes if m["active"]), None)
            if active:
                out["power"]["mode"] = active["name"]
                out["power"]["tariff"] = active["tariff"]
            try:
                d = c.der_comms()
                out["der_comms"] = {"sunsMdEn": d.get("sunsMdEn"), "sep2": d.get("enable")}
            except (OSError, TransportError, TimeoutError):
                pass
            out["firmware"] = {k: manifest.get(k)
                               for k in ("IBG_VER", "APP_VER", "protocolVer", "IBG_SN")
                               if k in manifest}
    except (OSError, TransportError, TimeoutError) as e:
        out["error"] = str(e)
    return out
