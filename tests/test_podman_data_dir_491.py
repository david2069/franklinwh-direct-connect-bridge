"""#491: under Podman (which makes /run/.containerenv, not /.dockerenv) the bridge is a
container too, so its data goes on the /data volume, not /app/data."""
from pathlib import Path

import pytest

from franklinwh_direct_connect_bridge import environment


@pytest.mark.parametrize("present,runtime", [
    ({"/data/options.json", "/.dockerenv"}, "ha_addon"),
    ({"/.dockerenv"}, "docker"),
    ({"/run/.containerenv"}, "docker"),          # Podman
    (set(), "dev"),
])
def test_runtime(monkeypatch, present, runtime):
    monkeypatch.setattr(Path, "exists", lambda self: str(self) in present)
    assert environment._detect() == runtime
