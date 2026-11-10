"""#219: libraries that drive the aGate are pinned to a tested version.

An open range (>=0.9) put every new franklinwh-modbus release into users' builds before it
was tested here: 0.9.6 and 0.10.0 arrived that way within two days (2026-10-17/18)."""
import pathlib
import re
from importlib.metadata import version

PYPROJECT = pathlib.Path(__file__).resolve().parents[1] / "pyproject.toml"


def _spec(name):
    m = re.search(rf'"{re.escape(name)}([^"]*)"', PYPROJECT.read_text())
    assert m, f"{name} missing from pyproject.toml"
    return m.group(1)


def test_franklinwh_modbus_is_pinned_exactly():
    assert re.fullmatch(r"==\d+\.\d+\.\d+", _spec("franklinwh-modbus")), _spec("franklinwh-modbus")


def test_the_suite_runs_on_the_pinned_version():
    """G0 is only evidence for the version it ran on."""
    assert version("franklinwh-modbus") == _spec("franklinwh-modbus")[2:]


def test_franklinwh_cloud_is_pinned_exactly():
    """#254: the cloud extra was an open range (>=0.4.9)."""
    m = re.search(r'"franklinwh-cloud([^"]*)"', PYPROJECT.read_text())
    assert m and re.fullmatch(r"==\d+\.\d+\.\d+", m.group(1)), m and m.group(1)
