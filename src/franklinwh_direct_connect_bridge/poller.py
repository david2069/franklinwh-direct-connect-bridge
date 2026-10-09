"""Background poller: read one aGate on an interval and publish to MQTT / HA.

One :func:`run_gateway` task runs per registered gateway. Each stores its identity, caches
and connectivity on its own :class:`~.state.GatewayState`, so multiple gateways never
collide (distinct serial → distinct HA device / node). Single-gateway is just one task
against the default gateway and behaves exactly as before.
"""

from __future__ import annotations

import asyncio
import logging
import time

from . import client
from . import providers
from .config import Settings
from .db import get_store
from .notify import Notifier, transitions
from . import notify_engine
from . import workers as _workers
from .publish import entities
from .publish.mqtt_publisher import MqttPublisher
from .state import GatewayState

log = logging.getLogger("franklinwh_direct_connect_bridge.poller")


async def run_gateway(settings: Settings, gw: GatewayState, stop: asyncio.Event) -> None:
    """Resolve THIS gateway from its firmware manifest, (optionally) connect MQTT, then
    read state every ``poll_interval`` until ``stop`` is set — publishing to MQTT when
    enabled and recording a history sample (tagged with this gateway's serial) when metrics
    are enabled. All blocking library/MQTT/DB calls run in a thread so the event loop stays
    free. MQTT is optional: if it's off (or fails to connect) the loop still runs to collect
    metrics. Crash-proof — a read/DB/MQTT error never kills the loop."""
    node, serial, fw = "agate", "", None

    async def _resolve_identity() -> None:
        """Read the firmware manifest for this gateway's serial — which is the MQTT
        node id, and therefore the Home Assistant device identity. Leaves the
        ``"agate"`` fallback in place if the read fails; never raises."""
        nonlocal node, serial, fw
        try:
            fwb = await asyncio.to_thread(client.firmware, settings, gw.active_host)
            serial = str(fwb.get("IBG_SN", ""))
            node = (serial or "agate").lower()
            fw = fwb.get("IBG_VER")
            gw.serial = serial or gw.serial
            gw.firmware = fw or gw.firmware
            _hw = fwb.get("SyHdVersion")
            if _hw is not None:
                gw.sy_hd_version = _hw
        except Exception as e:  # noqa: BLE001 — never crash the loop on a read
            log.warning("[%s] firmware read failed (using defaults): %s", gw.id, e)
        gw.node = node

    await _resolve_identity()

    def _start_mqtt():
        """Create + start an MqttPublisher (blocking connect). Raises on failure."""
        # Each gateway is a distinct serial node → distinct HA device (collision-free).
        device = entities.device_info(node, serial, fw)
        def _on_control(key: str, payload: str) -> None:
            """Inbound HA control. Runs on the MQTT network thread, so it is kept
            short and every outcome is logged — a control that silently fails is
            the thing this whole surface is trying to avoid."""
            from .publish import handle_command
            if not client.writes_enabled(settings):
                log.warning("[%s] control '%s' ignored — writes are disabled", gw.id, key)
                return
            try:
                result = handle_command(key, payload, settings=settings, client=client,
                                        host=gw.active_host)
                log.info("[%s] control %s=%s -> %s", gw.id, key, payload, result)
            except Exception as e:  # noqa: BLE001
                log.warning("[%s] control %s failed: %s", gw.id, key, e)

        pub = MqttPublisher(settings, node, device, command_handler=_on_control,
                            groups=entities.enabled_from_store(get_store(settings)))
        pub.start()
        return pub

    pub = None
    last_mqtt_try = 0.0
    _MQTT_RETRY_S = 60          # don't hammer a down broker — retry at most once a minute
    if settings.mqtt_enabled and getattr(gw, 'publish_ha', True) and not serial:
        # Do NOT publish discovery under the "agate" fallback. The node id IS the
        # Home Assistant device identity, so publishing it would:
        #   (a) leave a retained config for a device that never exists again once the
        #       real serial arrives — an orphan HA has no way to expire; and
        #   (b) in a multi-gateway install make EVERY unidentified gateway publish as
        #       the same node, merging them into one device.
        # The self-heal block below retries the identity read and starts MQTT then.
        log.warning("[%s] serial unknown — deferring MQTT discovery until the firmware "
                    "manifest reads (retrying every %ds)", gw.id, _MQTT_RETRY_S)
        last_mqtt_try = time.time()
    elif settings.mqtt_enabled and getattr(gw, 'publish_ha', True):
        try:
            pub = await asyncio.to_thread(_start_mqtt)
            gw.published_entities = len(pub.configs)
            log.info("[%s] MQTT publisher started for node=%s", gw.id, node)
        except Exception as e:  # noqa: BLE001 — metrics must keep collecting
            log.error("[%s] MQTT connect failed (%s:%s): %s — will retry every %ds",
                      gw.id, settings.mqtt_host, settings.mqtt_port, e, _MQTT_RETRY_S)
            pub = None
        last_mqtt_try = time.time()

    store = get_store(settings)
    if store is not None:
        log.info("[%s] metrics store active (%s)", gw.id, settings.metrics_db)

    notifier = Notifier(settings)
    prev: dict | None = None
    last_fw = fw
    inserts = 0
    fail_streak = 0   # consecutive failed polls (DEF-POLLER-STALL fix 1)
    _wname = f"poller:{gw.id}"
    try:
        while not stop.is_set():
            # Proof of life for this cycle (BR-36). DEGRADED while the aGate is
            # unreachable: the poller is working correctly and reporting a device
            # problem, which is not the same as the poller having died (BR-38).
            _workers.registry.beat(
                _wname,
                state=(_workers.WorkerState.DEGRADED if fail_streak
                       else _workers.WorkerState.RUNNING),
                detail=(f"{fail_streak} consecutive failed polls" if fail_streak else ""))
            # Self-heal: if MQTT never came up (broker was down at boot), retry — throttled —
            # instead of staying dead until a bridge restart.
            if settings.mqtt_enabled and pub is None and (time.time() - last_mqtt_try) >= _MQTT_RETRY_S:
                last_mqtt_try = time.time()
                if not serial:
                    await _resolve_identity()
                    if not serial:
                        log.debug("[%s] serial still unknown — discovery stays deferred", gw.id)
                if serial:                       # never publish under the fallback node
                    try:
                        pub = await asyncio.to_thread(_start_mqtt)
                        gw.published_entities = len(pub.configs)
                        log.info("[%s] MQTT publisher started for node=%s", gw.id, node)
                    except Exception as e:  # noqa: BLE001 — quiet on repeated failures
                        log.debug("[%s] MQTT still unreachable: %s", gw.id, e)
                        pub = None
            # Honor UI-requested (re-)publish / clear of HA discovery. Never crash the loop.
            if pub:
                try:
                    if gw.republish_requested:
                        _grp = entities.enabled_from_store(get_store(settings))
                        await asyncio.to_thread(pub.rebuild_discovery, _grp)
                        gw.published_entities = len(pub.configs)
                        log.info("[%s] re-published HA discovery (UI request)", gw.id)
                        gw.republish_requested = False
                    if gw.unpublish_requested:
                        await asyncio.to_thread(pub.clear_discovery)
                        log.info("[%s] cleared HA discovery entities (UI request)", gw.id)
                        gw.unpublish_requested = False
                except Exception as e:  # noqa: BLE001
                    log.warning("[%s] discovery (re/un)publish failed: %s", gw.id, e)
                gw.mqtt_connected = pub.is_connected()
            try:
                # One-session read; power already has entity keys + canonical mode label.
                # Bound the cycle (DEF-POLLER-STALL fix 2): a full summary is ping+Modbus
                # probes+login+~6 reads, ~70s against an unreachable aGate. Cap it so the loop
                # keeps cadence; a timeout is just a failed poll (ok:False), not a crash.
                _poll_timeout = max(10, min(settings.poll_interval, 30))
                try:
                    summ = await asyncio.wait_for(
                        asyncio.to_thread(client.summary, settings, gw.active_host),
                        timeout=_poll_timeout)
                except asyncio.TimeoutError:
                    summ = {"ok": False, "error": f"poll timed out after {_poll_timeout}s"}
                st = dict(summ.get("power", {}))
                st["latency_ms"] = summ.get("latency_ms")
                gw.last_state = st
                # Cache the full summary for /api/summary + /api/gateways/{id}/summary so the
                # dashboard reads the poller's copy instead of a fresh device session on every
                # browser poll (fixes flicker + slow load). Keep last-GOOD values but reflect
                # the CURRENT connectivity: on a failed poll, retain values and mark stale.
                if summ.get("ok"):
                    if fail_streak:
                        log.info("[%s] poll recovered after %d failed cycle(s)", gw.id, fail_streak)
                        fail_streak = 0
                    gw.last_summary = summ
                else:
                    fail_streak += 1
                    # First failure + every 10th thereafter — so an outage is self-evident in
                    # the (durable) log without flooding it. Recording pauses; last-good stays cached.
                    if fail_streak == 1 or fail_streak % 10 == 0:
                        log.warning("[%s] poll failed (%d in a row): %s — recording paused, "
                                    "last-good cached", gw.id, fail_streak,
                                    summ.get("error") or "unreachable")
                    if gw.last_summary:
                        gw.last_summary = {**gw.last_summary, "ok": False,
                                           "stale": True, "error": summ.get("error")}
                    else:
                        gw.last_summary = summ
                if pub:
                    pub.publish_state(st)
                    pub.publish_availability(bool(summ.get("ok")))
                for title, msg in transitions(prev, summ):
                    await asyncio.to_thread(notifier.notify, title, msg)
                # Configurable companion-push triggers + delivery log (FEAT-NOTIFY).
                try:
                    _st = get_store(settings)
                    if _st is not None:
                        _cfg = notify_engine.config(_st)
                        for ev, ttl, msg in notify_engine.evaluate(gw.label, summ, prev, _cfg):
                            await asyncio.to_thread(notify_engine.fire, _st, ev, ttl, msg, cfg=_cfg)
                except Exception as e:  # noqa: BLE001 — never let notifications break the poll
                    log.debug("notify engine pass failed: %s", e)
                prev = summ

                # Cloud-credential re-check. Reserve SoC is cloud-owned, so a revoked
                # password silently disables reserve control — and without this the
                # stale "valid" verdict would sit on screen until someone attempted a
                # write. Rate-limited to REVALIDATE_AFTER_S, skipped entirely when the
                # breaker is locked, and never allowed to disturb the poll loop.
                try:
                    if providers.revalidate_due(settings):
                        before = providers.cloud_auth_status().get("state")
                        # Bounded: the cloud library allows 30s per request and this
                        # makes up to three, so an unbounded call could stall the
                        # device poll loop for ~90s. A timeout is not an auth verdict.
                        after = (await asyncio.wait_for(
                            asyncio.to_thread(providers.validate_cloud, settings),
                            timeout=providers.VALIDATE_TIMEOUT_S)).get("state")
                        if after != before:
                            log.warning("cloud auth state %s -> %s", before, after)
                            if after in ("invalid", "locked"):
                                await asyncio.to_thread(
                                    notifier.notify,
                                    "FranklinWH cloud credentials rejected",
                                    "Reserve-SoC control is unavailable until the cloud "
                                    "credentials are corrected in Settings.")
                except asyncio.TimeoutError:
                    log.warning("cloud revalidation timed out after %ss — skipped",
                                providers.VALIDATE_TIMEOUT_S)
                except Exception as e:  # noqa: BLE001 — never kill the loop over this
                    log.debug("cloud revalidation skipped: %s", e)

                # Schedules run on the poll tick, so they inherit the poll interval —
                # a schedule cannot react faster than the bridge reads the gateway.
                # A scheduler fault must never stop polling.
                if store is not None and summ.get("ok"):
                    try:
                        from . import scheduler as _sched
                        # Reach the gateway by the host we KNOW (rediscovered active_host,
                        # else the configured IP) — not a bare active_host that may still be
                        # None. Mocks have no Modbus, so pass "" to skip the 702 ratings read.
                        _known_host = gw.active_host or gw.configured_host
                        _mb_host = "" if getattr(gw, "is_mock", False) else _known_host
                        fired = await asyncio.to_thread(
                            _sched.tick, settings=settings, client=client, store=store,
                            state=gw.last_state or {}, host=_known_host,
                            modbus_host=_mb_host, gateway_id=gw.id)
                        for f in fired:
                            log.info("[%s] schedule '%s' fired: %s",
                                     gw.id, f["name"], f["result"])
                    except Exception as e:  # noqa: BLE001
                        log.warning("[%s] scheduler tick failed: %s", gw.id, e)

                if summ.get("ok"):
                    fwb2 = summ.get("firmware") or {}
                    gw.serial = fwb2.get("IBG_SN") or gw.serial
                    # Record a history sample tagged with this gateway. A DB error must not
                    # kill the loop — log and continue.
                    if store is not None:
                        try:
                            await asyncio.to_thread(
                                store.insert, st, int(time.time()), gw.serial or gw.id,
                                summ.get("tou_tiers"))
                            inserts += 1
                            if inserts % 20 == 0:
                                deleted = await asyncio.to_thread(
                                    store.prune, settings.metrics_retention_days,
                                    int(time.time()))
                                if deleted > 0:
                                    log.info("[%s] pruned %d old metric rows", gw.id, deleted)
                        except Exception as e:  # noqa: BLE001
                            log.warning("[%s] metrics write failed: %s", gw.id, e)

                    fw_now = fwb2.get("IBG_VER")
                    if fw_now:
                        gw.firmware = fw_now
                    if last_fw and fw_now and fw_now != last_fw:   # OTA-change detection
                        log.warning("[%s] firmware changed: %s → %s", gw.id, last_fw, fw_now)
                        await asyncio.to_thread(
                            notifier.notify, "FranklinWH firmware updated",
                            f"{last_fw} → {fw_now}. Behaviours can differ — re-verify writes "
                            "and re-scan cmdTypes.")
                    if fw_now:
                        last_fw = fw_now
                else:                                              # re-discover on failure
                    newhost = await asyncio.to_thread(
                        client.rediscover, settings, gw.active_host, gw.serial)
                    if newhost:
                        gw.active_host = newhost
                        await asyncio.to_thread(
                            notifier.notify, "FranklinWH aGate moved",
                            f"Re-discovered on the LAN at {newhost}.")
            except Exception as e:  # noqa: BLE001
                log.warning("[%s] poll failed: %s", gw.id, e)
                if pub:
                    pub.publish_availability(False)
            try:
                await asyncio.wait_for(stop.wait(), timeout=settings.poll_interval)
            except asyncio.TimeoutError:
                pass
    except asyncio.CancelledError:
        raise
    except BaseException as exc:    # noqa: BLE001
        # Previously this loop had no `except`, so an unhandled exception ended the task
        # and nothing retrieved task.exception(). Polling, metrics, MQTT publishing and
        # (until phase 1) scheduling for this gateway all stopped together, permanently,
        # while /api/live still reported healthy because it does no gateway I/O. The
        # supervisor now sees it, but it must also be stated plainly in the log.
        log.exception("[%s] poller crashed — polling, metrics and publishing have STOPPED "
                      "for this gateway until it is restarted", gw.id)
        _workers.registry.beat(_wname, state=_workers.WorkerState.CRASHED,
                               detail=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        if pub:
            await asyncio.to_thread(pub.stop)
            log.info("[%s] MQTT publisher stopped", gw.id)
