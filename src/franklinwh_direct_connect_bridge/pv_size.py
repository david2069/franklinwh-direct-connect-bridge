"""The solar size the forecast and the analysis use (#583).

Derived by default: the gateways' own rating (1903 ``PV1RatedPower`` + ``PV2RatedPower``,
through System Setup), summed over the site's gateways as the forecast is per site. The
user's number wins when they set one: larger for DC panels above the AC rating or remote
solar the aGate doesn't rate, smaller for shading or clipping. With neither, None: nothing
is assumed (it used to be 5.0 kWp)."""
from __future__ import annotations


def derived_kwp(read: bool = False) -> float | None:
    """The gateways' reported solar size, summed; None when none reports one. Mock
    gateways count only when there is no real one. Without ``read`` only what System
    Setup last read is used, so the scheduler tick never waits on a gateway; the
    Settings page reads (``read=True``), as it always has."""
    from . import db, state, system_setup
    from .config import get_settings
    gws = list(state.gateways())
    real = [g for g in gws if not getattr(g, "is_mock", False)]
    total, seen = 0.0, False
    s = get_settings()
    # No gateway running yet: System Setup's own answer (read only).
    for gw in (real or gws or ([None] if read else [])):
        host = (gw.active_host or gw.configured_host) if gw else None
        try:
            if read:
                vals = system_setup.values(db.get_store(s), s, gw.id if gw else None, host)
                kwp = vals.get("solar_kwp") if "solar_kwp" in (vals.get("_derived") or {}) else None
            else:
                kwp = system_setup.reported_solar_kwp(host)
        except Exception:  # noqa: BLE001 — an unread gateway reports nothing
            continue
        if isinstance(kwp, (int, float)) and kwp > 0:
            total, seen = total + float(kwp), True
    return round(total, 2) if seen else None


def effective(settings, read: bool = False) -> dict:
    """``{kwp, source, derived}``: the user's size (source ``you``) when set, else the
    derived one (``gateway``), else None."""
    mine = getattr(settings, "pv_kwp", None)
    derived = derived_kwp(read)
    if isinstance(mine, (int, float)) and mine > 0:
        return {"kwp": float(mine), "source": "you", "derived": derived}
    return {"kwp": derived, "source": "gateway" if derived else None, "derived": derived}


def kwp(settings) -> float | None:
    return effective(settings)["kwp"]
