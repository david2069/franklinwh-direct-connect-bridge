"""In-process mock aGate emulators — one per mock gateway.

A mock gateway runs the library's threaded ``Emulator`` on ``127.0.0.1:<ephemeral>``
inside the bridge process (no container). The gateway's active host is set to
``127.0.0.1:<port>`` so the normal read plumbing reaches it (``client._split_hostport``
does the split). The mock synthesises the login + power/mode + full battery reads, so the
Battery tab (incl. multi-aPower) works; ``energy_history`` / ``smart_circuits`` are not
synthesised, so those views stay empty for a mock.
"""
from __future__ import annotations

import logging

from franklinwh_direct_connect_api.emulator import Emulator

log = logging.getLogger("franklinwh_direct_connect_bridge.mockgw")

_mocks: dict[str, Emulator] = {}


def seed_for(gw_id: str, mock_seed: int | None) -> int:
    """Explicit seed, else a stable non-zero seed derived from the gateway id (so the
    synthetic site — and its serial — are guaranteed and reproducible)."""
    if mock_seed:
        return int(mock_seed)
    return (abs(hash(gw_id)) % 90000) + 1


def start_mock(gw_id: str, *, seed: int, units: int,
               tz_offset_hours: float | None = None) -> str:
    """Start (or return the existing) emulator for a mock gateway.
    Returns the ``127.0.0.1:<port>`` host string to register.

    ``tz_offset_hours`` is the SITE's offset. Without it each mock takes a random
    per-seed timezone, so a site built from several mocks disagrees with itself about
    what hour it is — and anything deriving the site clock from a gateway gets a
    different answer per gateway.
    """
    emu = _mocks.get(gw_id)
    if emu is None:
        kw = {"host": "127.0.0.1", "port": 0, "seed": int(seed), "units": max(1, int(units))}
        try:
            emu = Emulator(**kw, tz_offset_hours=tz_offset_hours).start()
        except TypeError:
            # The installed library predates tz_offset_hours (added in
            # franklinwh-direct-connect-api after 0.4.0, which is what PyPI serves at the
            # time of writing). Adding a mock must not fail because an optional nicety is
            # missing — the mock simply keeps its own seeded clock. Measured on the live
            # add-on, 2026-10-15: this raised TypeError and the UI showed
            # "Internal Server Error" while leaving a half-built roster row behind.
            log.info("mock gateway %s: installed library has no tz_offset_hours — "
                     "using the seeded clock", gw_id)
            emu = Emulator(**kw).start()
        _mocks[gw_id] = emu
        log.info("mock gateway %s: emulator on 127.0.0.1:%d (seed=%d units=%d tz=%s)",
                 gw_id, emu.port, seed, units,
                 "per-seed" if tz_offset_hours is None else f"UTC{tz_offset_hours:+g}")
    return f"127.0.0.1:{emu.port}"


def stop_mock(gw_id: str) -> None:
    emu = _mocks.pop(gw_id, None)
    if emu is not None:
        try:
            emu.stop()
        except Exception:  # noqa: BLE001
            pass
        log.info("mock gateway %s: emulator stopped", gw_id)


def host_for(gw_id: str) -> str | None:
    emu = _mocks.get(gw_id)
    return f"127.0.0.1:{emu.port}" if emu is not None else None


def is_running(gw_id: str) -> bool:
    return gw_id in _mocks


def stop_all() -> None:
    for gid in list(_mocks):
        stop_mock(gid)
