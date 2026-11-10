"""franklinwh-modbus 0.13.0: closing the controller closes the TCP socket (library #138).

The bridge connects for every force, release, status and ratings read, then calls
``_close``. Before 0.13.0 the library's ``disconnect()`` called only pysunspec2's
``close()``, a no-op for TCP, so the aGate's single Modbus session stayed held until
garbage collection. Same sign as before for a watts force: 0.11.0 changed percent and
enums, not ``BatteryCommand(power_watts=...)``.
"""
from franklinwh_modbus import BatteryCommand, ControlMode
from franklinwh_modbus.controller import FranklinWHController

from franklinwh_direct_connect_bridge import battery_control as bc


class _Dev:
    def __init__(self):
        self.calls = []

    def disconnect(self):
        self.calls.append("disconnect")

    def close(self):
        self.calls.append("close")


def test_close_releases_the_agate_socket():
    c = FranklinWHController("192.0.2.10", port=502, unit_id=bc.UNIT_ID)
    dev = c.dev = _Dev()
    bc._close(c)
    assert "disconnect" in dev.calls
    assert c.dev is None


def test_a_watts_force_is_still_sent_as_watts():
    assert BatteryCommand(power_watts=1000).mode == ControlMode.WATTS
