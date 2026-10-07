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

from franklinwh_local.emulator import Emulator

log = logging.getLogger("franklinwh_direct_connect_bridge.mockgw")

_mocks: dict[str, Emulator] = {}


def seed_for(gw_id: str, mock_seed: int | None) -> int:
    """Explicit seed, else a stable non-zero seed derived from the gateway id (so the
    synthetic site — and its serial — are guaranteed and reproducible)."""
    if mock_seed:
        return int(mock_seed)
    return (abs(hash(gw_id)) % 90000) + 1


def start_mock(gw_id: str, *, seed: int, units: int) -> str:
    """Start (or return the existing) emulator for a mock gateway.
    Returns the ``127.0.0.1:<port>`` host string to register."""
    emu = _mocks.get(gw_id)
    if emu is None:
        emu = Emulator(host="127.0.0.1", port=0, seed=int(seed), units=max(1, int(units))).start()
        _mocks[gw_id] = emu
        log.info("mock gateway %s: emulator on 127.0.0.1:%d (seed=%d units=%d)",
                 gw_id, emu.port, seed, units)
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
