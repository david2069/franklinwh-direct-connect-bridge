"""The SITE's clock — the aGate's wall-clock, which is the only one schedules may use.

``docs/TIMEZONES.md`` is the contract: a schedule *rule* ("charge at 2 PM") is authored in
site time, not in the container's. Those were the same thing only because the standalone
compose file mounts ``/etc/localtime``; as a Home Assistant add-on nothing sets a timezone
at all, and a gateway can in any case sit in a different zone from the host running this.

Everything here returns TIMEZONE-AWARE datetimes, fixed to the site's offset. That is the
point: a naive site-local datetime looks identical to a naive container-local one, and
``.timestamp()`` would silently resolve it against the container's zone — the scheduler has
a dozen such conversions. Aware datetimes make every one of them correct without a dozen
call sites having to remember.
"""
from __future__ import annotations

import datetime as dt
import logging
import threading

log = logging.getLogger(__name__)

#: How long an offset may be reused. Short on purpose: TIMEZONES.md requires offsets be
#: derived live and never cached across a DST boundary. Ten minutes bounds the error at one
#: tick-interval's worth of wrong decisions twice a year, against reading 1201 every tick.
TTL_SECONDS = 600

#: The real range of UTC offsets in use: UTC-12:00 (Baker Island) to UTC+14:00 (Kiritimati).
#: Anything outside it is not a timezone — it is a gateway whose clock is wrong (a mock
#: answering with a capture's date did exactly that, putting the offset 571 days out).
#: ``dt.timezone`` refuses an offset of 24h or more, so an unchecked value does not produce
#: a bad schedule, it raises and kills the tick that was supposed to run the schedule.
MIN_OFFSET_MINUTES = -12 * 60
MAX_OFFSET_MINUTES = 14 * 60

_lock = threading.Lock()
_cache: dict[str | None, tuple[float, int]] = {}      # host -> (expires_at, offset_minutes)
#: The last offset each host reported, kept past the TTL. When the gateway cannot be read the
#: site is still in the zone it was in a moment ago — far likelier than the container's (#161).
_last: dict[str | None, int] = {}
_fallback_logged: set = set()


def _offset_from_reading(tl: dict) -> int | None:
    """Site offset in minutes from a ``time_location`` (1201) reading.

    The aGate's own wall-clock minus UTC is authoritative and DST-correct. ``timezoneStr``
    is usually empty, so an IANA name is not available; ``timezone`` is the BASE offset and
    ignores DST, so it is only a fallback.
    """
    t = tl.get("time")
    if t:
        try:
            local = dt.datetime.strptime(t, "%Y-%m-%d %H:%M:%S")
            utc_now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
            off = int(round((local - utc_now).total_seconds() / 60 / 15) * 15)
            if _plausible(off):
                return off
            # The clock is wrong, not the zone. Fall through to the base offset rather
            # than returning a number no caller can build a timezone from.
            log.warning("site clock implausible: aGate says %s, which is %d minutes from "
                        "UTC — ignoring it and using the reported base offset", t, off)
        except (ValueError, TypeError):
            pass
    base = tl.get("timezone")
    if isinstance(base, (int, float)):
        off = int(base) * 60
        return off if _plausible(off) else None
    return None


def _plausible(offset: int) -> bool:
    """Is this a UTC offset a place on Earth actually uses?"""
    return MIN_OFFSET_MINUTES <= offset <= MAX_OFFSET_MINUTES


def offset_minutes(settings, host: str | None = None, *, store=None) -> int | None:
    """Minutes to add to UTC to get site wall-clock, or None when the aGate is unreadable.

    None is deliberate and is NOT 0: "we could not ask" must stay distinguishable from
    "the site is at UTC", so a caller can fall back knowingly instead of silently
    scheduling against the wrong clock.
    """
    now = dt.datetime.now(dt.timezone.utc).timestamp()
    with _lock:
        hit = _cache.get(host)
        if hit and hit[0] > now:
            return hit[1]
    try:
        from . import client as _client
        tl = _client.read(settings, "time_location", host=host)
    except Exception:                                          # noqa: BLE001 — never fail a tick
        return None
    off = _offset_from_reading(tl or {})
    if off is None:
        return None
    with _lock:
        _cache[host] = (now + TTL_SECONDS, off)
        _last[host] = off
        _fallback_logged.discard(host)
    return off


def now_site(settings, host: str | None = None) -> tuple[dt.datetime, int | None]:
    """``(aware now in the site's zone, offset)``, or container-local with offset ``None``.

    When the gateway cannot be read, the last offset it reported is used and logged (#161);
    only a gateway never read falls back to the container's clock, which is what the
    scheduler did before this existed. Either way the result is aware, so nothing
    downstream has to care which it got.
    """
    off = offset_minutes(settings, host)
    if off is None:
        with _lock:
            off = _last.get(host)
            first = off is not None and host not in _fallback_logged
            if first:
                _fallback_logged.add(host)
        if off is None:
            return dt.datetime.now().astimezone(), None
        if first:
            log.warning("site clock unreadable for %s — using its last known offset, "
                        "%+d minutes from UTC", host or "the default gateway", off)
    return dt.datetime.now(dt.timezone(dt.timedelta(minutes=off))), off


def now_known(host: str | None = None) -> dt.datetime:
    """Site now from the offset the scheduler last read for ``host``, without asking the
    gateway — for previews (next fire, timeline, Test) that must agree with the tick but
    must not add a gateway round trip to a page load. Container-local until one is known."""
    with _lock:
        off = _last.get(host)
    if off is None:
        return dt.datetime.now().astimezone()
    return dt.datetime.now(dt.timezone(dt.timedelta(minutes=off)))


def reset_cache() -> None:
    """Drop cached offsets (tests, and a gateway whose host changed)."""
    with _lock:
        _cache.clear()
        _last.clear()
        _fallback_logged.clear()
