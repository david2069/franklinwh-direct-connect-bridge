"""#427: the demo mocks start on a port the library allows, under its current command name.

franklinwh-direct-connect-api 0.5.1 refuses ``emulate --port 9000`` (reserved for a real
aGate and the official Gateway Emulator), so both mocks restarted in a loop on a fresh
build. The ``franklinwh-local`` alias is due for removal, so the demo uses
``franklinwh-direct-connect``. The demo bridge must reach the mocks on the same port.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEMO = (ROOT / "docker-compose.demo.yml").read_text()
FRESH = (ROOT / "docker-compose.demo-fresh.yml").read_text()


def emulate_ports():
    cmds = re.findall(r"^\s*command:\s*(.*emulate.*)$", DEMO, re.M)
    assert len(cmds) == 2
    for c in cmds:
        assert c.startswith("franklinwh-direct-connect emulate "), c
    return {int(re.search(r"--port (\d+)", c).group(1)) for c in cmds}


def test_the_mocks_avoid_the_reserved_port():
    assert 9000 not in emulate_ports()


def test_the_demo_bridge_reaches_the_mocks_on_their_port():
    (port,) = emulate_ports()
    for text in (DEMO, FRESH):
        assert re.findall(r"FWH_PORT=(\d+)", text) == [str(port)]
