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

from . import alerts
from . import client
from . import providers
from .config import Settings, metrics_active
from .db import get_store
from .notify import Notifier, transitions
from . import notify_engine
from . import workers as _workers
from .publish import entities
from .publish.mqtt_publisher import MqttPublisher
from .state import GatewayState, gateways as _all_gateways

log = logging.getLogger("franklinwh_direct_connect_bridge.poller")

#: gateway id -> ts of the last Modbus client result recorded as a link sample (#221).
_MB_RECORDED: dict[str, float] = {}


def _record_modbus_leg(store, gw_id: str, summ: dict) -> bool:
    """Record the ``modbus_502`` link sample, once per new result. True if recorded.

    The summary carries the Modbus client's LAST real result, not a probe (#221).
    Recording it every poll would log one measurement as many fresh samples. None is
    "not measured" (client off, a mock, no connection yet): nothing is recorded, rather
    than inventing an outage out of our own configuration. The sample is dated when it
    was measured, with no expected cadence: these results are sparse by design, so the
    gaps between them are not missed polls."""
    mb = summ.get("modbus_502")
    mb_at = summ.get("modbus_502_at")
    if mb is None or not mb_at or mb_at == _MB_RECORDED.get(gw_id):
        return False
    _MB_RECORDED[gw_id] = mb_at
    store.record_link_probe(gw_id, "ok" if mb else "failed", leg="modbus_502",
                            error="" if mb else "port 502 not open", now=mb_at)
    return True


def _fmt_outage(seconds: float | None) -> str:
    """An outage length in words. '4920s' is a number; '1h 22m' is an answer."""
    if seconds is None:
        return "an outage of unknown length"
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m {s % 60}s"
    return f"{s // 3600}h {(s % 3600) // 60}m"


#: Re-discovery (#123): failed polls in a row before a sweep is even considered, and the
#: back-off between sweeps while the gateway stays gone.
REDISCOVER_AFTER_FAILS = 3
SWEEP_GAP_MIN_S = 300
SWEEP_GAP_MAX_S = 3600

#: How often the aGate's network state is read for Home Assistant (#134).
NET_EVERY_S = 600


async def run_gateway(settings: Settings, gw: GatewayState, stop: asyncio.Event) -> None:
    """Resolve THIS gateway from its firmware manifest, (optionally) connect MQTT, then
    read state every ``poll_interval`` until ``stop`` is set — publishing to MQTT when
    enabled and recording a history sample (tagged with this gateway's serial) when metrics
    are enabled. All blocking library/MQTT/DB calls run in a thread so the event loop stays
    free. MQTT is optional: if it's off (or fails to connect) the loop still runs to collect
    metrics. Crash-proof — a read/DB/MQTT error never kills the loop."""
    node, serial, fw = "agate", "", None
    notifier = Notifier(settings)
    _wname = f"poller:{gw.id}"

    async def _identity_ok(reported: str) -> bool:
        """The aGate's serial is locked to this gateway the first time it is reported
        (#381). A serial another gateway owns, or one different from the locked serial,
        stops this gateway: its readings are not recorded or published and nothing is
        written to it, because it is not the aGate this gateway is. Logged and notified."""
        if not reported:
            return True
        if gw.serial_locked and (gw.serial or "").upper() == reported.upper():
            return True
        store = get_store(settings)
        outcome, detail = await asyncio.to_thread(store.lock_gateway_serial, gw.id, reported)
        if outcome in ("locked", "ok"):
            if outcome == "locked":
                log.info("[%s] serial %s locked to this gateway", gw.id, detail)
            gw.serial, gw.serial_locked = detail, True
            return True
        if outcome == "unregistered":      # no roster row to lock it in
            gw.serial = reported
            return True
        where = gw.active_host or gw.configured_host
        if outcome == "mismatch":
            why = (f"Gateway '{gw.label or gw.id}' ({gw.id}) is locked to aGate {detail}, "
                   f"but {where} reported {reported}. Stopped. If the aGate was replaced, "
                   "remove this gateway and add it again.")
        else:
            why = (f"aGate {reported} at {where} already belongs to gateway {detail}. "
                   f"Gateway '{gw.label or gw.id}' ({gw.id}) is stopped.")
        gw.identity_error = why
        log.error("[%s] %s", gw.id, why)
        _workers.registry.beat(_wname, state=_workers.WorkerState.STOPPED, detail=why)
        try:
            await asyncio.to_thread(notifier.notify, "FranklinWH gateway stopped", why)
        except Exception as e:  # noqa: BLE001
            log.debug("[%s] identity notice not sent: %s", gw.id, e)
        return False

    async def _resolve_identity() -> None:
        """Read the firmware manifest for this gateway's serial — which is the MQTT
        node id, and therefore the Home Assistant device identity. Leaves the
        ``"agate"`` fallback in place if the read fails; never raises."""
        nonlocal node, serial, fw
        try:
            fwb = await asyncio.to_thread(client.firmware, settings,
                                          gw.active_host or gw.configured_host)
            serial = str(fwb.get("IBG_SN", ""))
            if not await _identity_ok(serial):
                return
            node = (serial or "agate").lower()
            fw = fwb.get("IBG_VER")
            gw.firmware = fw or gw.firmware
            _hw = fwb.get("SyHdVersion")
            if _hw is not None:
                gw.sy_hd_version = _hw
        except Exception as e:  # noqa: BLE001 — never crash the loop on a read
            log.warning("[%s] firmware read failed (using defaults): %s", gw.id, e)
        gw.node = node

    await _resolve_identity()
    if gw.identity_error:
        return

    # Publishing OFF means nothing of ours is left in Home Assistant. Until #98 a gateway
    # with publishing off (every mock, by default) was published anyway; once the flag is
    # honoured those devices would sit "unavailable" for ever. Remove whatever is still
    # retained for this node — verified, and a no-op when there is nothing.
    if settings.mqtt_enabled and not getattr(gw, "publish_ha", True) and serial:
        try:
            from .publish import purge as _purge
            res = await asyncio.to_thread(_purge.purge, settings, node)
            if res.get("found"):
                log.warning("[%s] publishing is off: removed %s retained topic(s) left in Home "
                            "Assistant (%s left)", gw.id, res.get("removed"), len(res.get("left") or []))
        except Exception as e:  # noqa: BLE001 — a broker problem must not stop polling
            log.debug("[%s] publish-off clean-up skipped: %s", gw.id, e)

    def _start_mqtt():
        """Create + start an MqttPublisher (blocking connect). Raises on failure."""
        # Each gateway is a distinct serial node → distinct HA device (collision-free).
        from . import devicedb as _ddb
        _hw = getattr(gw, "sy_hd_version", None)
        _model = ((_ddb.gateway(_hw) or {}).get("model") if _hw is not None else None)
        device = entities.device_info(node, serial, fw, model=_model,
                                      is_mock=bool(getattr(gw, "is_mock", False)))
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
                                        host=gw.active_host or gw.configured_host)
                log.info("[%s] control %s=%s -> %s", gw.id, key, payload, result)
            except Exception as e:  # noqa: BLE001
                log.warning("[%s] control %s failed: %s", gw.id, key, e)

        pub = MqttPublisher(settings, node, device, command_handler=_on_control,
                            groups=entities.enabled_from_store(get_store(settings)),
                            skip=(entities.NETWORK_KEYS if getattr(gw, "is_mock", False)
                                  else frozenset()))
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

    # The handle this loop RECORDS history through. The store itself is always open (it
    # holds the roster and settings, #81); metrics_active only decides whether samples and
    # link probes are written here.
    store = get_store(settings) if metrics_active(settings) else None
    if store is not None:
        log.info("[%s] metrics store active (%s)", gw.id, settings.metrics_db)

    net_state: dict = {}
    net_last = 0.0
    next_sweep = 0.0
    sweep_gap = SWEEP_GAP_MIN_S
    prev: dict | None = None
    last_fw = fw
    inserts = 0
    fail_streak = 0   # consecutive failed polls (DEF-POLLER-STALL fix 1)
    starting_since: float | None = None   # first all-zero start-up frame of a run (#309)
    alerts_sig: tuple | None = None   # last alert summary published to MQTT (#271)
    alerts_pub_ts = 0.0
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
            # publish_ha is checked HERE too: this retry used to start MQTT for a gateway
            # whose publishing is off, so a mock created with publish_ha=False was in
            # Home Assistant within one poll (#98).
            if (settings.mqtt_enabled and getattr(gw, 'publish_ha', True) and pub is None
                    and (time.time() - last_mqtt_try) >= _MQTT_RETRY_S):
                last_mqtt_try = time.time()
                # Re-ask the Supervisor first. Auto-config runs once at startup, so an
                # add-on installed before Mosquitto kept retrying the SAME unset broker
                # for ever and never noticed when Mosquitto appeared. No-op off-add-on,
                # and it leaves user-supplied credentials alone.
                try:
                    from .ha_supervisor import apply_supervisor_mqtt as _apply_sup
                    await asyncio.to_thread(_apply_sup, settings)
                except Exception as e:  # noqa: BLE001 — never break the poll loop
                    log.debug("[%s] Supervisor MQTT re-check failed: %s", gw.id, e)
                if not serial:
                    await _resolve_identity()
                    if gw.identity_error:
                        break
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
            # MQTT_DOWN (#271): only where this gateway is meant to publish and has an
            # identity to publish under; a deferred or switched-off publisher is not down.
            _want_mqtt = bool(settings.mqtt_enabled and getattr(gw, 'publish_ha', True)
                              and serial)
            alerts.set_condition(
                gw.id, "MQTT_DOWN", _want_mqtt and not (pub and pub.is_connected()),
                detail=f"Not connected to the MQTT broker {settings.mqtt_host}:"
                       f"{settings.mqtt_port}; Home Assistant entities are not updating")
            # Bridge problem (#271): on a change of the alert summary, and at least every
            # HEARTBEAT_EVERY_S (checked once per poll cycle). The heartbeat itself is the
            # alert monitor's, bridge-level, not this gateway's.
            if pub:
                try:
                    _ast = get_store(settings)
                    _asum = _ast.alert_summary() if _ast is not None else {}
                    _asig = (_asum.get("level"), _asum.get("open"), _asum.get("latest_id"),
                             _asum.get("changed_ts"))
                    if _asig != alerts_sig or \
                            time.time() - alerts_pub_ts >= entities.HEARTBEAT_EVERY_S:
                        _open = _ast.alerts(open_only=True) if _ast is not None else []
                        await asyncio.to_thread(pub.publish_alerts, entities.alerts_payload(
                            _asum, _open, gw.id))
                        alerts_sig, alerts_pub_ts = _asig, time.time()
                except Exception as e:  # noqa: BLE001 — never break the poll loop
                    log.debug("[%s] bridge problem not published: %s", gw.id, e)
            try:
                # One-session read; power already has entity keys + canonical mode label.
                # Bound the cycle (DEF-POLLER-STALL fix 2): a full summary is ping+Modbus
                # probes+login+~6 reads, ~70s against an unreachable aGate. Cap it so the loop
                # keeps cadence; a timeout is just a failed poll (ok:False), not a crash.
                _poll_timeout = max(10, min(settings.poll_interval, 30))
                try:
                    summ = await asyncio.wait_for(
                        asyncio.to_thread(client.summary, settings,
                                          gw.active_host or gw.configured_host,
                                          mock=bool(getattr(gw, 'is_mock', False))),
                        timeout=_poll_timeout)
                except asyncio.TimeoutError:
                    summ = {"ok": False, "error": f"poll timed out after {_poll_timeout}s"}
                if summ.get("ok") and not await _identity_ok(
                        str((summ.get("firmware") or {}).get("IBG_SN") or "")):
                    break
                # An all-zero start-up frame after a reboot or reconnect (#309): client.py
                # has blanked its values. It is neither recorded nor published, so history
                # and Home Assistant never get a 0 W that was not a reading.
                starting = bool(summ.get("ok") and (summ.get("power") or {}).get("agate_starting"))
                if starting and starting_since is None:
                    starting_since = time.time()
                    log.warning("[%s] aGate reconnecting: it reports all zeros (start-up frame) "
                                "— not recorded or published until real readings return", gw.id)
                elif not starting and starting_since is not None and summ.get("ok"):
                    log.info("[%s] aGate readings returned after %.0f s of start-up frames",
                             gw.id, time.time() - starting_since)
                    starting_since = None
                st = entities.state_payload(summ)   # the keys HA's templates read (#96)
                # aGate network (#134): a separate light read every NET_EVERY_S, never every
                # poll (the aGate is sensitive to load, #123), and never for a mock.
                if not getattr(gw, "is_mock", False) and summ.get("ok") and \
                        time.time() - net_last >= NET_EVERY_S:
                    net_last = time.time()
                    try:
                        nb = await asyncio.wait_for(asyncio.to_thread(
                            client.network_light, settings,
                            gw.active_host or gw.configured_host), timeout=_poll_timeout)
                        from .cloud_compat import network_from_interfaces as _nfi
                        from .publish.network import network_state as _ns
                        raw = nb.get("interfaces_raw")
                        net_state = _ns(nb.get("connectivity"),
                                        _nfi(raw) if isinstance(raw, dict) else None,
                                        nb.get("switches"), nb.get("cloud"))
                    except Exception as e:  # noqa: BLE001 — a network read never breaks the poll
                        log.debug("[%s] network read failed: %s", gw.id, e)
                st.update(net_state)
                gw.last_state = st
                # Only a poll that READ the gateway makes the snapshot fresh (#284). A
                # failed poll stored an empty snapshot as new, so the scheduler kept
                # evaluating a dead gateway and blocked its tick on that gateway's clock
                # read (three 20 s connects) — stalling every other gateway's schedules.
                if summ.get("ok"):
                    gw.state_ts = time.time()
                # Cache the full summary for /api/summary + /api/gateways/{id}/summary so the
                # dashboard reads the poller's copy instead of a fresh device session on every
                # browser poll (fixes flicker + slow load). Keep last-GOOD values but reflect
                # the CURRENT connectivity: on a failed poll, retain values and mark stale.
                # Record the probe BEFORE acting on it (RUNTIME_DESIGN §6.9). A
                # timeout is kept distinct from a refusal: "connection refused" is the
                # device answering, a timeout is nobody answering, and flattening both
                # to False is what let the UI report Offline beside live values.
                err = str(summ.get("error") or "")
                if summ.get("ok"):
                    outcome = "ok"
                elif "timed out" in err.lower() or "timeout" in err.lower():
                    outcome = "unknown"
                else:
                    outcome = "failed"
                # Alert facts (#271), recorded whether or not metrics are on; the alert
                # monitor applies the thresholds. No address means not set up yet (#265),
                # which is not an outage.
                if gw.active_host:
                    alerts.set_condition(
                        gw.id, "GATEWAY_UNREACHABLE", outcome != "ok",
                        detail=f"{gw.label or gw.id} is not answering on the LAN: "
                               f"{err or 'unreachable'}")
                    # Only while the gateway ANSWERS: unreachable is GATEWAY_UNREACHABLE,
                    # and raising both for one fault doubled the modal (G1, 2026-10-21).
                    alerts.set_condition(
                        gw.id, "LIVE_DATA_MISSING", outcome == "ok" and not summ.get("power"),
                        detail=f"No live data from {gw.label or gw.id}: "
                               f"{err or 'the power read failed'}")
                if store is not None:
                    try:
                        # All THREE legs the cycle already measured. Recording one and
                        # calling the card "Connection history" could not say which
                        # connection it meant — and ping and :502 were being measured
                        # and thrown away every poll.
                        def _record_legs():
                            interval = float(settings.poll_interval or 30)
                            main = store.record_link_probe(
                                gw.id, outcome, leg="local_9000",
                                latency_ms=summ.get("latency_ms"), error=err,
                                expected_interval_s=interval,
                                # Reported by the call that did the connecting, not
                                # assumed here — so connects_per_probe tells the truth
                                # today (1.0, a fresh socket + login every poll) and
                                # falls on its own when a held session lands.
                                connects=int(summ.get("connects") or 0))
                            # ping is informational: None means "not measured", which is
                            # not the same as a failure and must not be recorded as one.
                            png = summ.get("ping")
                            if png is not None:
                                store.record_link_probe(
                                    gw.id, "ok" if png else "failed", leg="icmp",
                                    error="" if png else "no ICMP reply",
                                    expected_interval_s=interval)
                            _record_modbus_leg(store, gw.id, summ)   # #221
                            return main
                        link = await asyncio.to_thread(_record_legs)
                        gw.link_state = link["state"]
                        # Log on the TRANSITION only. Logging the state every cycle is
                        # the alert-spam failure this design exists to prevent.
                        if link["transition"] == "down":
                            log.warning("[%s] link DOWN after %d consecutive failed probes: %s",
                                        gw.id, link["consecutive_failures"], err or "unreachable")
                        elif link["transition"] == "up":
                            log.info("[%s] link RECOVERED after %s",
                                     gw.id, _fmt_outage(link.get("outage_s")))
                    except Exception as e:  # noqa: BLE001 — bookkeeping must not stop polling
                        log.debug("[%s] link history not recorded: %s", gw.id, e)
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
                    if not starting:
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

                # The scheduler no longer runs here. It was a passenger on this loop,
                # which meant it inherited the poll interval as its resolution and died
                # with its host — one gateway's failure stopped ALL scheduling. It is now
                # its own worker (scheduler_worker.py) reading the snapshot stamped above.

                if summ.get("ok"):
                    fwb2 = summ.get("firmware") or {}
                    # Record a history sample tagged with this gateway. A DB error must not
                    # kill the loop — log and continue.
                    if store is not None and not starting:
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
                elif not getattr(gw, "is_mock", False):            # re-discover on failure
                    # A /24 sweep is heavy on a struggling aGate and the Wi-Fi (#123). Sweep
                    # only when the gateway has really gone from its address: several failed
                    # polls in a row AND its known address answers neither ping nor :9000.
                    # Then back off (5 → 10 → … 60 min) while it stays gone.
                    now = time.time()
                    if fail_streak >= REDISCOVER_AFTER_FAILS and now >= next_sweep:
                        here = await asyncio.to_thread(client.still_at_address,
                                                     gw.active_host or gw.configured_host)
                        if here:
                            log.info("[%s] %s still answers — not sweeping the network",
                                     gw.id, gw.active_host)
                        else:
                            next_sweep = now + sweep_gap
                            sweep_gap = min(sweep_gap * 2, SWEEP_GAP_MAX_S)
                            # Hosts the other gateways use are never adopted (#356).
                            taken = {h for g in _all_gateways() if g.id != gw.id
                                     for h in (g.active_host, g.configured_host) if h}
                            newhost = await asyncio.to_thread(
                                client.rediscover, settings,
                                gw.active_host or gw.configured_host, gw.serial,
                                taken=taken)
                            if newhost and newhost != gw.active_host:   # it really moved
                                gw.active_host = newhost
                                await asyncio.to_thread(
                                    notifier.notify, "FranklinWH aGate moved",
                                    f"{gw.label or gw.id} re-discovered on the LAN at {newhost}.")
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
