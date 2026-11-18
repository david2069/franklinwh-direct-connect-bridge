"""Battery wear from hems (#713 step 4, #612 §6).

- **Warranty inputs** are setup fields per gateway (Settings → Gateways → Battery warranty
  & wear). The FranklinWH cloud's ``warrantyInfo`` only pre-fills the end date and
  warranted throughput, marked please confirm (``hems.wear.setup_fields``); it is read at
  most once a day while the cloud is signed in, and only those figures are kept (no
  installer details).
- **SoH** is the mean of the aPower SoH the alarm pass already reads.
- **Dispatch events:** each poll goes into ``hems.wear.add_sample``; the events it closes
  are kept in ``wear_events``.
- **Round-trip efficiency** from ``hems.wear.soc_matched_cycles`` on the aGate's own daily
  charge and discharge counters (``kwh_fhp_chg`` / ``kwh_fhp_di``), made cumulative across
  midnight, sampled every few minutes into ``wear_samples``.

Read-only towards the aGate: nothing here writes to a battery. Never raises into the poll.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import statistics
import time

from hems import wear as hwear

log = logging.getLogger(__name__)

#: app_config: the user's values, per gateway.
KEY = "wear:{gw}"
#: app_config: the cloud's warranty figures and the day they were read, per gateway.
CLOUD_KEY = "wear_cloud:{gw}"
#: The cloud's warrantyInfo fields kept (no installer or contact details).
CLOUD_FIELDS = ("expirationTime", "throughput", "remainThroughput")
#: A sample for the efficiency cycles at most this often (s).
SAMPLE_EVERY_S = 300
#: Samples are kept this long (s): the efficiency median spans 30 days, a cycle at most 7.
SAMPLES_KEEP_S = 45 * 86400

_trackers: dict[str, dict] = {}         # gateway -> hems tracker
_last_sample: dict[str, float] = {}     # gateway -> ts of the last stored sample


def _json(store, key: str) -> dict:
    try:
        v = store.get_config(key) if store is not None else None
        return json.loads(v) if v else {}
    except Exception:                                            # noqa: BLE001
        return {}


# ── Setup fields ─────────────────────────────────────────────────────────────────

def values(store, gateway_id: str) -> dict:
    return _json(store, KEY.format(gw=gateway_id))


def save(store, gateway_id: str, body: dict) -> dict:
    """Set fields (null clears one back to its pre-fill). Unknown keys: ValueError."""
    bad = [k for k in body if k not in hwear.FIELDS]
    if bad:
        raise ValueError(f"unknown wear field(s): {', '.join(bad)}")
    cur = values(store, gateway_id)
    for k, v in body.items():
        if v in (None, ""):
            cur.pop(k, None)
        else:
            cur[k] = v
    store.set_config(KEY.format(gw=gateway_id), json.dumps(cur))
    return cur


def cloud_subset(result: dict | None) -> dict | None:
    """Only the warranty figures from a warrantyInfo ``result``."""
    if not isinstance(result, dict):
        return None
    out = {k: result[k] for k in CLOUD_FIELDS if result.get(k) not in (None, "")}
    return out or None


def _read_cloud(settings, serial: str) -> dict | None:
    """One warrantyInfo read on the login the cloud status loop shares."""
    import asyncio

    from . import cloud_status

    async def _run():
        async with await cloud_status._client_for(
                settings.fwh_cloud_email, settings.fwh_cloud_password,
                serial, source="wear") as cloud:
            return await cloud.get_warranty_info()

    data = asyncio.run(_run())
    return (data or {}).get("result") if isinstance(data, dict) else None


def cloud(store, settings, gateway_id: str, serial: str | None, now: float, *,
          read=None) -> dict | None:
    """The cloud's warranty figures for this gateway, read at most once a day and only
    while the cloud is signed in; the last good read otherwise. Never raises."""
    from . import providers
    k = CLOUD_KEY.format(gw=gateway_id)
    cur = _json(store, k)
    day = dt.date.fromtimestamp(now).isoformat()
    signed_in = (providers.cloud_auth_status() or {}).get("state") == "valid"
    if signed_in and serial and cur.get("day") != day:
        try:
            got = cloud_subset((read or _read_cloud)(settings, serial))
            if got:
                cur = {"day": day, "warranty": got}
                store.set_config(k, json.dumps(cur))
        except Exception as e:                                   # noqa: BLE001
            log.debug("wear: cloud warranty not read: %s", e)
    return cur.get("warranty")


def fields(store, gateway_id: str, *, cloud: dict | None = None) -> dict:
    """hems's setup fields: the user's value, else the cloud's pre-fill to confirm."""
    return hwear.setup_fields(values(store, gateway_id), cloud=cloud)


# ── Poll: dispatch events and efficiency samples ─────────────────────────────────

def observe(store, gateway_id: str, ts: float, power: dict) -> None:
    """One poll's battery power, SoC, counters and temperature. Never raises."""
    if store is None or not power:
        return
    try:
        tr = _trackers.setdefault(gateway_id, hwear.new_tracker())
        bw = power.get("battery_w")
        closed = hwear.add_sample(
            tr, ts, battery_w=float(bw) if isinstance(bw, (int, float)) else None,
            soc=power.get("soc"), source="vpp" if power.get("vpp") else None,
            ambient_temp_c=power.get("t_amb"))
        for ev in closed:
            store.wear_event_add(gateway_id, ev)
        if ts - _last_sample.get(gateway_id, 0) >= SAMPLE_EVERY_S - 1:
            if dt.date.fromtimestamp(ts) != dt.date.fromtimestamp(_last_sample.get(gateway_id, 0)):
                store.wear_samples_prune(ts - SAMPLES_KEEP_S)        # once a day
            _last_sample[gateway_id] = ts
            store.wear_sample_add(gateway_id, ts, soc=power.get("soc"),
                                  chg_kwh=power.get("kwh_fhp_chg"),
                                  dis_kwh=power.get("kwh_fhp_di"),
                                  power_w=bw if isinstance(bw, (int, float)) else None,
                                  temp_c=power.get("t_amb"))
    except Exception as e:                                       # noqa: BLE001
        log.debug("[%s] wear sample not recorded: %s", gateway_id, e)


def cumulative(samples: list[dict]) -> list[dict]:
    """hems's ``{ts, soc, charged_kwh, discharged_kwh, power_w, temp_c}`` from samples of
    the aGate's daily counters: a counter that falls (midnight) carries its last value on."""
    out, base_c, base_d, last_c, last_d = [], 0.0, 0.0, None, None
    for s in samples:
        c, d = s.get("chg"), s.get("dis")
        if c is None or d is None:
            continue
        if last_c is not None and c < last_c - 1e-6:
            base_c += last_c
        if last_d is not None and d < last_d - 1e-6:
            base_d += last_d
        last_c, last_d = c, d
        out.append({"ts": s["ts"], "soc": s.get("soc"), "charged_kwh": base_c + c,
                    "discharged_kwh": base_d + d, "power_w": s.get("power_w"),
                    "temp_c": s.get("temp_c")})
    return out


def efficiency(store, gateway_id: str, now: float) -> dict:
    """hems's rolling round-trip efficiency from SoC-matched cycles."""
    since = now - (hwear.EFFICIENCY_DAYS + 7) * 86400
    cyc = hwear.soc_matched_cycles(cumulative(store.wear_samples(gateway_id, since)))
    return hwear.efficiency(cyc, now_ts=now)


# ── The report ───────────────────────────────────────────────────────────────────

def _soh(gateway_id: str) -> float | None:
    from . import state
    gw = state.get_gateway(gateway_id)
    soh = [float(v) for v in ((getattr(gw, "apower_soh", None) or {}).values())
           if isinstance(v, (int, float))]
    return round(statistics.fmean(soh), 2) if soh else None


def _used_kwh(store, gateway_id: str, install_date: str | None) -> float | None:
    """Discharged since the install date, from the daily snapshots (#Health)."""
    rows = store.health_snapshots(gateway_id, days=40 * 365)
    vals = [r["battery_discharged_wh"] for r in rows
            if r.get("battery_discharged_wh") is not None
            and (not install_date or r["day"] >= str(install_date)[:10])]
    return round(sum(vals) / 1000, 3) if vals else None


def report(store, settings, gateway_id: str, now: float | None = None, *,
           cloud_fn=None) -> dict:
    """Everything the Battery warranty & wear card shows for this gateway."""
    from . import state
    now = time.time() if now is None else now
    gw = state.get_gateway(gateway_id)
    cl = (cloud_fn or cloud)(store, settings, gateway_id, getattr(gw, "serial", None), now)
    f = fields(store, gateway_id, cloud=cl)
    used = _used_kwh(store, gateway_id, f["install_date"]["value"])
    remaining = hwear.remaining_kwh(
        f, used_kwh=used,
        cloud_remaining_kwh=(cl or {}).get("remainThroughput")
        if f["warranted_throughput_mwh"]["source"] != "user" else None)
    return {
        "fields": f,
        "cost": hwear.cost_per_kwh(f),
        "used_kwh": used,
        "remaining_kwh": remaining,
        "pace": hwear.pace(remaining_kwh=remaining, today=dt.date.fromtimestamp(now),
                           warranty_end=f["warranty_end"]["value"]),
        "soh_pct": _soh(gateway_id),
        "efficiency": efficiency(store, gateway_id, now),
        "events": store.wear_events(gateway_id, limit=10),
    }
