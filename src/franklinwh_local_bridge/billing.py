"""Per-meter billing engine (FEAT-BILLING-SERVICE) — Phases 2-3: demand, energy
cost, export bonus + export charge.

Ports the Modbus bridge's DemandTracker, ADAPTED to the local data source: the
local API exposes power samples (grid_w), not the monotonic grid_import_wh/
grid_export_wh counters the Modbus version deltas. So we INTEGRATE grid power over
the sample interval — import = max(0, grid_w), export = max(0, -grid_w) — into
energy, and price each delta against the rate in force at that instant (rate_model).
State persists to the metrics store's app_config KV so a restart keeps the period's
running totals. Informational (express-don't-enforce): all outputs are sensors,
never a gate on dispatch.

Runs whenever the gateway's meter has a tariff (for energy cost); demand / bonus /
export-charge outputs appear only when that tariff configures the matching window.
"""
from __future__ import annotations

import calendar
import datetime as dt
import json
from typing import Any

_KEY_PREFIX = "billing_state:"
_PERSIST_EVERY_S = 60.0
_DEFAULT_INTERVAL_MIN = 30


def _num(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _period_start(now: dt.datetime, cycle_day: int) -> dt.datetime:
    cycle_day = max(1, min(31, int(cycle_day or 1)))
    day = min(cycle_day, calendar.monthrange(now.year, now.month)[1])
    start = now.replace(day=day, hour=0, minute=0, second=0, microsecond=0)
    if start > now:
        y, m = (now.year, now.month - 1) if now.month > 1 else (now.year - 1, 12)
        start = start.replace(year=y, month=m, day=min(cycle_day, calendar.monthrange(y, m)[1]))
    return start


def _period_end(ps: dt.datetime, cycle_day: int) -> dt.datetime:
    y, m = (ps.year, ps.month + 1) if ps.month < 12 else (ps.year + 1, 1)
    return ps.replace(year=y, month=m, day=min(int(cycle_day or 1), calendar.monthrange(y, m)[1]))


def _in_window(win: Any, now: dt.datetime) -> bool:
    from . import scheduler
    return scheduler._in_window(win, now)


class BillingTracker:
    """One gateway's running billing state over the current period. Fed (grid_w, now)
    each tick; integrates + prices; rolls over at the billing cycle day."""

    def __init__(self) -> None:
        self._s = self._blank()
        self._last_persist = 0.0
        self._loaded = False

    @staticmethod
    def _blank() -> dict[str, Any]:
        return {
            "period_start": None,
            "last_ts": None,
            "interval_start": None,
            "interval_import_wh": 0.0,
            "peak_kwh": 0.0,
            "tariff_id": None,
            "period_import_kwh": 0.0,
            "import_cost": 0.0,
            "export_credit": 0.0,
            "unpriced_import_kwh": 0.0,
            "unpriced_export_kwh": 0.0,
            "bonus_export_wh": 0.0,
            "charge_export_wh": 0.0,
        }

    def _load(self, store, gw: str) -> None:
        if self._loaded or store is None:
            return
        self._loaded = True
        try:
            raw = store.get_config(_KEY_PREFIX + gw)
            if raw:
                stored = json.loads(raw)
                self._s.update({k: stored.get(k, v) for k, v in self._blank().items()})
        except Exception:                                       # noqa: BLE001
            pass

    def _persist(self, store, gw: str, now_ts: float) -> None:
        if store is None or now_ts - self._last_persist < _PERSIST_EVERY_S:
            return
        self._last_persist = now_ts
        try:
            store.set_config(_KEY_PREFIX + gw, json.dumps(self._s))
        except Exception:                                       # noqa: BLE001
            pass

    @staticmethod
    def _rate(cfg: dict, now: dt.datetime, used_kwh: float, dynamic_rate: dict | None = None) -> dict:
        """buy/sell in force now for the running tiered consumption, or {} on error.
        A ``dynamic_rate`` (live wholesale {buy, sell} in $/kWh) OVERRIDES the static tariff —
        this is the FEAT-BILLING-WHOLESALE dynamic-tariff path (AusNEM / HA price entity)."""
        if dynamic_rate and dynamic_rate.get("buy") is not None:
            buy = dynamic_rate.get("buy")
            sell = dynamic_rate.get("sell")
            return {"season": None, "time_period": None, "time_period_label": "Wholesale (live)",
                    "buy": buy, "sell": sell, "tier": None,
                    "billable": bool(buy is not None and buy > 0.0), "reason": "dynamic"}
        try:
            from . import rate_model
            pr = cfg.get("pricing") or {}
            return rate_model.resolve(pr.get("seasons"), now, used_kwh, pr.get("default_rate")) or {}
        except Exception:                                       # noqa: BLE001
            return {}

    def _interval_min(self, cfg: dict) -> int:
        d = cfg.get("demand") or {}
        iv = int(_num(d.get("interval_min"), _DEFAULT_INTERVAL_MIN)) or _DEFAULT_INTERVAL_MIN
        return iv if iv in (15, 30, 60) else _DEFAULT_INTERVAL_MIN

    def update(self, store, gw: str, grid_w: float | None, cfg: dict, now: dt.datetime,
               dynamic_rate: dict | None = None) -> None:
        self._load(store, gw)
        now_ts = now.timestamp()
        cycle_day = int(cfg.get("cycle_day", 1) or 1)
        interval_min = self._interval_min(cfg)

        # period rollover — snapshot the CLOSING period into history before blanking.
        ps = _period_start(now, cycle_day).timestamp()
        if self._s["period_start"] is None:
            self._s["period_start"] = ps
        elif self._s["period_start"] != ps:
            self._close_period(store, gw, cfg, now)
            self._s = self._blank()
            self._s["period_start"] = ps
        # tariff change (supersede) → the accrued numbers belong to the OLD tariff; close + reset.
        tid = cfg.get("tariff_id")
        if self._s.get("tariff_id") is not None and self._s["tariff_id"] != tid:
            self._close_period(store, gw, cfg, now)
            self._s = self._blank()
            self._s["period_start"] = ps
        self._s["tariff_id"] = tid

        # demand interval bucket
        slot = now.replace(minute=(now.minute // interval_min) * interval_min,
                           second=0, microsecond=0).timestamp()
        st = self._s["interval_start"]
        if st is None:
            self._s["interval_start"] = slot
        elif slot != st:
            prev_kwh = self._s["interval_import_wh"] / 1000.0
            dwin = (cfg.get("demand") or {}).get("window")
            if _in_window(dwin, dt.datetime.fromtimestamp(st)):
                self._s["peak_kwh"] = max(self._s["peak_kwh"], prev_kwh)
            self._s["interval_import_wh"] = 0.0
            self._s["interval_start"] = slot

        # integrate + price the delta since the last sample
        last_ts = self._s["last_ts"]
        if last_ts is not None and grid_w is not None:
            dt_s = now_ts - last_ts
            if 0 < dt_s <= 3600:                               # ignore gaps > 1 h
                gw_f = float(grid_w)
                imp_wh = max(0.0, gw_f) * dt_s / 3600.0
                exp_wh = max(0.0, -gw_f) * dt_s / 3600.0
                self._s["interval_import_wh"] += imp_wh
                # price import against consumption BEFORE this delta (tiered basis)
                rate = self._rate(cfg, now, self._s["period_import_kwh"], dynamic_rate)
                d_imp = imp_wh / 1000.0
                if d_imp > 0:
                    self._s["period_import_kwh"] += d_imp
                    if rate.get("buy") is None:
                        self._s["unpriced_import_kwh"] += d_imp
                    else:
                        self._s["import_cost"] += d_imp * rate["buy"]
                d_exp = exp_wh / 1000.0
                if d_exp > 0:
                    if rate.get("sell") is None:
                        self._s["unpriced_export_kwh"] += d_exp
                    else:
                        self._s["export_credit"] += d_exp * rate["sell"]
                    if cfg.get("bonus") and _in_window(cfg["bonus"]["window"], now):
                        self._s["bonus_export_wh"] += exp_wh
                    if cfg.get("charge") and _in_window(cfg["charge"]["window"], now):
                        self._s["charge_export_wh"] += exp_wh
        self._s["last_ts"] = now_ts
        self._persist(store, gw, now_ts)

    def as_points(self, cfg: dict, now: dt.datetime) -> dict[str, Any]:
        s = self._s
        out: dict[str, Any] = {
            "energy.period_import_kwh": round(s["period_import_kwh"], 3),
            "energy.import_cost": round(s["import_cost"], 4),
            "energy.export_credit": round(s["export_credit"], 4),
            "energy.unpriced_import_kwh": round(s["unpriced_import_kwh"], 3),
            "energy.unpriced_export_kwh": round(s["unpriced_export_kwh"], 3),
        }
        ps_ts, days, period_days = s["period_start"], 0.0, 0.0
        if ps_ts is not None:
            ps = dt.datetime.fromtimestamp(ps_ts)
            days = round(max(0.0, (now - ps).total_seconds() / 86400.0), 3)
            period_days = round((_period_end(ps, int(cfg.get("cycle_day", 1) or 1)) - ps).total_seconds() / 86400.0, 3)

        if cfg.get("demand"):
            interval_min = self._interval_min(cfg)
            out["demand.peak_kw"] = round(s["peak_kwh"] * (60.0 / interval_min), 3)
            interval_kw = 0.0
            st = s["interval_start"]
            if st is not None:
                elapsed_h = max(1.0 / 3600.0, (now.timestamp() - st) / 3600.0)
                interval_kw = round(s["interval_import_wh"] / 1000.0 / elapsed_h, 3)
            out["demand.interval_kw"] = interval_kw
            rate = _num(cfg["demand"].get("rate"))
            basis = cfg["demand"].get("charge_basis") or "per_kw_day"
            out["demand.period_charge"] = round(out["demand.peak_kw"] * rate * (days if basis == "per_kw_day" else 1.0), 2)

        if cfg.get("bonus"):
            bonus_kwh = round(s["bonus_export_wh"] / 1000.0, 3)
            out["bonus.export_kwh"] = bonus_kwh
            out["bonus.period_credit"] = round(bonus_kwh * _num(cfg["bonus"].get("rate")), 2)

        if cfg.get("charge"):
            charge_kwh = round(s["charge_export_wh"] / 1000.0, 3)
            free = round(_num(cfg["charge"].get("free_kwh_per_day")) * period_days, 3)
            net = round(max(0.0, charge_kwh - free), 3)
            out["tariff.export_charge_kwh"] = charge_kwh
            out["tariff.export_charge_free_remaining"] = round(max(0.0, free - charge_kwh), 3)
            out["tariff.export_charge_net_kwh"] = net
            out["tariff.export_charge_cost"] = round(net * _num(cfg["charge"].get("rate")), 2)
        return out

    def _close_period(self, store, gw: str, cfg: dict, now: dt.datetime, force: bool = False) -> None:
        """Persist the CLOSING period to ``billing_periods`` before the state is blanked on
        rollover / tariff change. Skips an empty period (unless ``force``, a manual close);
        never raises. ``self._s`` still holds the old period here, so ``as_points`` reports its
        final numbers."""
        if store is None:
            return
        s = self._s
        ps_ts = s.get("period_start")
        if not ps_ts:
            return
        if not force and (s.get("period_import_kwh", 0) <= 0 and s.get("import_cost", 0) <= 0
                and s.get("export_credit", 0) <= 0 and s.get("bonus_export_wh", 0) <= 0):
            return  # nothing accrued — don't clutter history (auto-close only)
        try:
            pts = self.as_points(cfg, now)
            gwid = None if gw == "default" else gw
            fixed_total = 0.0
            try:
                fx = fixed_snapshot(store, gwid, now)
                fixed_total = _num(fx.get("fixed.period_total"))
            except Exception:                                   # noqa: BLE001
                fixed_total = 0.0
            import_cost = _num(pts.get("energy.import_cost"))
            export_credit = _num(pts.get("energy.export_credit"))
            demand_charge = _num(pts.get("demand.period_charge"))
            bonus_credit = _num(pts.get("bonus.period_credit"))
            export_charge = _num(pts.get("tariff.export_charge_cost"))
            net = round(import_cost - export_credit + demand_charge + export_charge
                        + fixed_total - bonus_credit, 2)
            meta = _period_meta(store, gwid)
            ps = dt.datetime.fromtimestamp(ps_ts)
            pe = _period_end(ps, int(cfg.get("cycle_day", 1) or 1))
            store.record_billing_period(
                gateway_id=gwid, meter_id=meta.get("meter_id"),
                utility_id=meta.get("utility_id"), tariff_id=s.get("tariff_id"),
                retailer=meta.get("retailer"), network=meta.get("network"),
                plan_version=meta.get("plan_version"), tariff_name=meta.get("tariff_name"),
                period_start=ps_ts, period_end=pe.timestamp(),
                import_kwh=_num(pts.get("energy.period_import_kwh")), import_cost=import_cost,
                export_credit=export_credit, demand_peak_kw=_num(pts.get("demand.peak_kw")),
                demand_charge=demand_charge, bonus_credit=bonus_credit,
                export_charge=export_charge, fixed_total=fixed_total, net_total=net)
        except Exception:                                       # noqa: BLE001 — never break the tick
            pass


def _period_meta(store, gateway_id) -> dict:
    """Retailer / network / plan / tariff-name for stamping a closed period (so a year of
    history reads correctly across a provider or tariff switch)."""
    out = {"meter_id": None, "utility_id": None, "retailer": None, "network": None,
           "plan_version": None, "tariff_name": None}
    try:
        from . import scheduler
        meter = scheduler._meter_for_gateway(store, gateway_id)
        if not meter:
            return out
        out["meter_id"] = meter.get("id")
        tar = store.tariff(meter.get("tariff_id")) if meter.get("tariff_id") else None
        if tar:
            out["tariff_name"] = tar.get("name")
            out["plan_version"] = tar.get("plan_version")
            out["utility_id"] = tar.get("utility_id")
        uid = out["utility_id"] or meter.get("utility_id")
        util = store.utility(uid) if uid else None
        if util:
            out["utility_id"] = util.get("id")
            out["retailer"] = util.get("name")
            out["network"] = util.get("network_dnsp")
    except Exception:                                           # noqa: BLE001
        pass
    return out


_TRACKERS: dict[str, BillingTracker] = {}


def _billing_cfg(store, gateway_id) -> dict | None:
    """Resolve the gateway's meter → tariff into the billing config, or None if no
    tariff. demand/bonus/charge are None unless the tariff configures that window."""
    from . import scheduler
    meter = scheduler._meter_for_gateway(store, gateway_id)
    if not meter:
        return None
    try:
        tar = store.tariff(meter.get("tariff_id")) if meter.get("tariff_id") else None
    except Exception:                                           # noqa: BLE001
        tar = None
    if not tar:
        return None
    pricing = tar.get("pricing") if isinstance(tar.get("pricing"), dict) else {}
    cfg: dict[str, Any] = {
        "pricing": pricing,
        "cycle_day": int(_num(tar.get("billing_cycle_day"), 1)) or 1,
        "tariff_id": tar.get("id"),
        "demand": None, "bonus": None, "charge": None,
    }
    dw = tar.get("demand_window")
    if isinstance(dw, dict) and dw:
        cfg["demand"] = {"window": dw, "rate": _num(pricing.get("demand_rate")),
                         "interval_min": int(_num(pricing.get("demand_interval_min"), 30)) or 30,
                         "charge_basis": pricing.get("demand_charge_basis") or "per_kw_day"}
    bw = tar.get("bonus_window")
    if isinstance(bw, dict) and bw:
        cfg["bonus"] = {"window": bw, "rate": _num(pricing.get("export_bonus_rate"))}
    cw = tar.get("charge_window")
    if isinstance(cw, dict) and cw:
        cfg["charge"] = {"window": cw, "rate": _num(pricing.get("export_charge_rate")),
                         "free_kwh_per_day": _num(pricing.get("export_charge_free_kwh_per_day"))}
    return cfg


def billing_tick(store, gateway_id=None, grid_w: float | None = None,
                 now: dt.datetime | None = None,
                 dynamic_rate: dict | None = None) -> dict[str, Any]:
    """Feed this tick's grid power and return all configured billing sensors. Empty
    when the gateway's meter has no tariff."""
    now = now or dt.datetime.now()
    cfg = _billing_cfg(store, gateway_id)
    if cfg is None:
        return {}
    key = gateway_id or "default"
    tr = _TRACKERS.get(key) or _TRACKERS.setdefault(key, BillingTracker())
    tr.update(store, key, grid_w, cfg, now, dynamic_rate)
    return tr.as_points(cfg, now)


FIXED_FREQUENCIES = ("daily", "weekly", "monthly", "quarterly", "annual")


def _daily_equiv(freq: str, rate: float, days_in_period: float) -> float:
    dip = days_in_period or 30.0
    return {"daily": rate, "weekly": rate / 7.0, "monthly": rate / dip,
            "quarterly": rate / (dip * 3.0), "annual": rate / (dip * 12.0)}.get(freq, 0.0)


def fixed_snapshot(store, gateway_id=None, now: dt.datetime | None = None) -> dict[str, Any]:
    """Standing/fixed charges accrued this period — deterministic (no meter data), so a
    pure function of `now` + the tariff's fixed_charges [{frequency, rate, tax_rate, ...}].
    Empty when the tariff has none. Tax-inclusive (rate x (1 + tax_rate))."""
    now = now or dt.datetime.now()
    from . import scheduler
    meter = scheduler._meter_for_gateway(store, gateway_id)
    if not meter:
        return {}
    try:
        tar = store.tariff(meter.get("tariff_id")) if meter.get("tariff_id") else None
    except Exception:                                           # noqa: BLE001
        tar = None
    charges = tar.get("fixed_charges") if tar else None
    if not isinstance(charges, list) or not charges:
        return {}
    cycle_day = int(_num(tar.get("billing_cycle_day"), 1)) or 1
    ps = _period_start(now, cycle_day)
    pe = _period_end(ps, cycle_day)
    days_in_period = round((pe - ps).total_seconds() / 86400.0, 3) or 30.0
    days_elapsed = min(round(max(0.0, (now - ps).total_seconds() / 86400.0), 3), days_in_period)
    daily = 0.0
    for c in charges:
        if not isinstance(c, dict):
            continue
        freq = c.get("frequency") if c.get("frequency") in FIXED_FREQUENCIES else "daily"
        daily += _daily_equiv(freq, _num(c.get("rate")), days_in_period) * (1.0 + _num(c.get("tax_rate")))
    daily = round(daily, 4)
    period_total = round(daily * days_in_period, 2)
    accrued = round(daily * days_elapsed, 2)
    return {
        "fixed.daily_charge": daily,
        "fixed.accrued_period": accrued,
        "fixed.period_total": period_total,
        "fixed.remaining": round(max(0.0, period_total - accrued), 2),
        "fixed.days_remaining": round(max(0.0, days_in_period - days_elapsed), 3),
    }


def billing_read(store, gateway_id=None, now: dt.datetime | None = None) -> dict[str, Any]:
    """Read the running billing sensors WITHOUT feeding a sample — Test/timeline
    preview, so on-demand reads don't perturb the tick-driven integration."""
    now = now or dt.datetime.now()
    cfg = _billing_cfg(store, gateway_id)
    if cfg is None:
        return {}
    key = gateway_id or "default"
    tr = _TRACKERS.get(key)
    if tr is None:
        tr = BillingTracker()
        tr._load(store, key)
    return tr.as_points(cfg, now)


def force_close_current(store, gateway_id=None, now: dt.datetime | None = None) -> dict[str, Any]:
    """Snapshot the CURRENT running period into ``billing_periods`` now — a manual early
    close so the user sees this period's itemised breakdown without waiting for rollover.
    Does NOT blank the tracker (accrual continues); the automatic rollover close later
    REPLACES the row (same gateway+period_start) with the final numbers. Returns
    {ok, closed, period?} or {ok:false, reason}."""
    now = now or dt.datetime.now()
    cfg = _billing_cfg(store, gateway_id)
    if cfg is None:
        return {"ok": False, "reason": "no tariff assigned to this meter"}
    key = gateway_id or "default"
    gwid = None if key == "default" else key
    tr = _TRACKERS.get(key)
    if tr is None:
        tr = _TRACKERS.setdefault(key, BillingTracker())
        tr._load(store, key)
    s = tr._s
    # A tracker that hasn't ticked since boot has no period_start — anchor it on the
    # current cycle so a fixed-charge-only period can still be closed.
    if not s.get("period_start"):
        s["period_start"] = _period_start(now, int(cfg.get("cycle_day", 1) or 1)).timestamp()
    # A period with any real cost — energy OR a standing charge — is a genuine bill.
    pts = tr.as_points(cfg, now)
    fixed_total = 0.0
    try:
        fixed_total = _num(fixed_snapshot(store, gwid, now).get("fixed.period_total"))
    except Exception:                                           # noqa: BLE001
        fixed_total = 0.0
    net = (_num(pts.get("energy.import_cost")) - _num(pts.get("energy.export_credit"))
           + _num(pts.get("demand.period_charge")) + _num(pts.get("tariff.export_charge_cost"))
           + fixed_total - _num(pts.get("bonus.period_credit")))
    if abs(net) < 0.005 and _num(pts.get("energy.period_import_kwh")) <= 0:
        return {"ok": False, "reason": "nothing has accrued in this period yet"}
    tr._close_period(store, key, cfg, now, force=True)
    rows = store.billing_periods(limit=1, gateway_id=gwid) or []
    return {"ok": True, "closed": True, "period": (rows[0] if rows else None)}


def fetch_modbus_history(base_url: str, username: str = "admin", password: str = "admin",
                         *, timeout: float = 10.0) -> list[dict]:
    """Log in to a Modbus bridge and pull its closed billing periods (``/api/tariff/history``).
    Returns the periods list (newest first). Raises on network/auth failure — the caller reports
    it. Server-side call to a user-configured host (same pattern as providers.py)."""
    import http.cookiejar
    import urllib.request

    base = (base_url or "").rstrip("/")
    if not base.startswith(("http://", "https://")):
        base = "http://" + base
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    login = urllib.request.Request(  # noqa: S310 — user-configured host
        base + "/api/auth/login",
        data=json.dumps({"username": username, "password": password}).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    opener.open(login, timeout=timeout).read()
    with opener.open(base + "/api/tariff/history?limit=240", timeout=timeout) as r:  # noqa: S310
        data = json.loads(r.read().decode())
    return data.get("periods") or []


def import_modbus_periods(store, periods, gateway_id=None,
                          tariff_name_default: str = "Imported (Modbus Bridge)") -> dict[str, Any]:
    """Backfill closed billing periods from the Modbus bridge's ``/api/tariff/history`` rows
    into our ``billing_periods`` (the aGate is the same physical device). Maps the Modbus
    column names to ours, skips degenerate (end<=start) and all-zero periods, and dedups by
    (gateway, period_start) so a re-import is idempotent. Returns {ok, imported, skipped}."""
    gwid = None if (gateway_id in (None, "", "default")) else gateway_id
    imported = skipped = 0
    for p in periods or []:
        ps, pe = _num(p.get("period_start")), _num(p.get("period_end"))
        if not ps or not pe or pe <= ps:                       # degenerate/empty span
            skipped += 1
            continue
        import_cost = _num(p.get("energy_cost"))
        export_credit = _num(p.get("energy_credit"))
        bonus_credit = _num(p.get("reward_credit"))
        export_charge = _num(p.get("charge_cost"))
        fixed_total = _num(p.get("fixed_charges"))
        demand_charge = _num(p.get("demand_charge"))
        net_total = _num(p.get("net_total"))
        if not any(abs(v) > 0.0049 for v in (import_cost, export_credit, bonus_credit,
                                             export_charge, fixed_total, demand_charge, net_total)):
            skipped += 1                                        # nothing billed — don't clutter
            continue
        pv = p.get("plan_version")
        store.record_billing_period(
            gateway_id=gwid, period_start=ps, period_end=pe,
            retailer=(p.get("retailer") or None), network=(p.get("network") or None),
            plan_version=(str(pv) if pv is not None else None),
            tariff_name=(p.get("tariff_name") or tariff_name_default),
            demand_peak_kw=_num(p.get("demand_peak_kw")), demand_charge=demand_charge,
            import_cost=import_cost, export_credit=export_credit,
            bonus_credit=bonus_credit, export_charge=export_charge,
            fixed_total=fixed_total, net_total=net_total)
        imported += 1
    return {"ok": True, "imported": imported, "skipped": skipped}
