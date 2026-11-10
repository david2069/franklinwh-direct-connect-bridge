"""#224 — connecting to the aGate must not write to it.

franklinwh-modbus 0.9.5 ``connect()`` runs a write test on 15507-15509 (operating mode and
reserves) on every connect. This drives the library's REAL ``connect()`` over a fake
transport that records every Modbus frame, and checks that the bridge's connection sends
no write (function 6 or 16). On 0.9.5 the library itself wrote on connect; the pinned 0.9.6
does not, so the second test checks the library and the first the bridge's guard."""
import struct

import pytest

pytest.importorskip("franklinwh_modbus")
import franklinwh_modbus.controller as lib  # noqa: E402

from franklinwh_direct_connect_bridge import battery_control as bc  # noqa: E402


class _Sock:
    def __init__(self, frames):
        self.frames = frames
        self._last = None

    def sendall(self, req):
        self.frames.append(req)
        self._last = req

    def recv(self, n):
        tid, proto, _len, unit, fn = struct.unpack(">HHHBB", self._last[:8])
        if fn == 3:                       # a read of one register: answer 1
            return struct.pack(">HHHBBBH", tid, proto, 5, unit, 3, 2, 1)
        return self._last[:12]            # echo a write, as a Modbus server does


class _Client:
    def __init__(self, frames):
        self.socket = _Sock(frames)

    def connect(self):
        return True

    def close(self):
        pass


class _Device:
    frames: list = []

    def __init__(self, **kw):
        self.client = _Client(_Device.frames)
        self.models = {}

    def scan(self, *a, **kw):
        pass

    def write(self, addr, data):
        # pysunspec2's device write. franklinwh-modbus 0.12.0+ wraps it on connect (its
        # write trace), so the fake needs one; a call is recorded as a function 16 frame.
        self.client.socket.sendall(struct.pack(">HHHBBHH", 0, 0, 7 + len(data), 1, 16, addr,
                                               len(data) // 2) + bytes(data))

    def close(self):
        pass


@pytest.fixture
def frames(monkeypatch):
    _Device.frames = []
    monkeypatch.setattr(lib, "SunSpecModbusClientDeviceTCP", _Device)
    monkeypatch.setattr(bc, "effective_target", lambda host: ("192.0.2.10", 502))
    return _Device.frames


def _writes(frames):
    return [f for f in frames if len(f) >= 8 and f[7] in (6, 16)]


def test_the_pinned_library_writes_nothing_on_connect(frames):
    """The pinned franklinwh-modbus (0.9.6, its #24) no longer runs the write test in
    connect(). Without the bridge's guard, connect() must still send no write. On 0.9.5
    this sent 15507-15509 (#224), which is what the guard below exists for."""
    c = lib.FranklinWHController("192.0.2.10", port=502, unit_id=1)
    assert c.connect()
    assert _writes(frames) == [], [f.hex() for f in _writes(frames)]


def test_the_bridge_connect_writes_nothing(frames):
    c, _ = bc._connect("192.0.2.10")
    assert _writes(frames) == [], [f.hex() for f in _writes(frames)]
    assert c._test_extension_writability()["skipped"]
