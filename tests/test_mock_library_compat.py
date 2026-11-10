"""Adding a mock must not fail because the installed library is older.

Live add-on, 2026-10-15: "defect can't add mock gateways — Internal Server Error". The
add-on installs franklinwh-direct-connect-api from PyPI, which served 0.4.0 — a version
without the `tz_offset_hours` parameter added later. `Emulator(tz_offset_hours=...)` raised
TypeError, the API returned 500, and a half-built roster row was left behind.

The bridge pins a newer library now, but the lesson stands: an optional nicety must degrade,
not take the feature down with it.
"""
import pytest

from franklinwh_direct_connect_bridge import mockgw


class _OldEmulator:
    """Stands in for the pre-tz_offset_hours library."""
    instances = []

    def __init__(self, host="127.0.0.1", port=0, seed=0, units=1):
        self.port = 45678
        self.seed = seed
        self.units = units
        _OldEmulator.instances.append(self)

    def start(self):
        return self

    def stop(self):
        pass


class _NewEmulator(_OldEmulator):
    def __init__(self, host="127.0.0.1", port=0, seed=0, units=1, tz_offset_hours=None):
        super().__init__(host=host, port=port, seed=seed, units=units)
        self.tz = tz_offset_hours


@pytest.fixture(autouse=True)
def _clean():
    mockgw.stop_all()
    _OldEmulator.instances = []
    yield
    mockgw.stop_all()


def test_an_older_library_still_gets_a_mock(monkeypatch):
    monkeypatch.setattr(mockgw, "Emulator", _OldEmulator)
    host = mockgw.start_mock("g1", seed=7, units=2, tz_offset_hours=10)
    assert host == "127.0.0.1:45678"              # it started, rather than raising
    assert mockgw.is_running("g1")


def test_the_site_clock_is_still_used_when_the_library_supports_it(monkeypatch):
    monkeypatch.setattr(mockgw, "Emulator", _NewEmulator)
    mockgw.start_mock("g2", seed=7, units=2, tz_offset_hours=10.5)
    assert _OldEmulator.instances[-1].tz == 10.5


def test_a_real_failure_still_surfaces(monkeypatch):
    """Degrading on TypeError must not swallow a genuine startup failure."""
    class _Broken(_OldEmulator):
        def start(self):
            raise OSError("address already in use")
    monkeypatch.setattr(mockgw, "Emulator", _Broken)
    with pytest.raises(OSError):
        mockgw.start_mock("g3", seed=1, units=1, tz_offset_hours=10)
