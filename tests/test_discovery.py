"""Phase 3 — re-discovery picks the right host. Every call names its host (#379)."""

from types import SimpleNamespace as NS

import pytest

from franklinwh_direct_connect_bridge import client
from franklinwh_direct_connect_bridge.config import Settings


def test_no_host_raises_instead_of_using_the_configured_one():
    """#379: an empty host no longer falls back to fwh_host or the default gateway."""
    s = Settings(fwh_host="192.0.2.110")
    with pytest.raises(ValueError, match="no aGate host"):
        client._client(s, None)
    with pytest.raises(ValueError, match="no aGate host"):
        client.health(s)


def test_rediscover_prefers_matching_serial(monkeypatch):
    s = Settings(fwh_host="192.0.2.110")
    hits = [
        NS(host="192.0.2.5", sendmqtt_confirmed=True, manifest={"IBG_SN": "SN-OTHER"}),
        NS(host="192.0.2.240", sendmqtt_confirmed=True, manifest={"IBG_SN": "SN-KNOWN"}),
    ]
    monkeypatch.setattr(client.discover, "expand_targets", lambda subnet: ["x"])
    monkeypatch.setattr(client.discover, "scan", lambda *a, **k: hits)
    # matched by serial, not first hit
    assert client.rediscover(s, "192.0.2.110", "SN-KNOWN") == "192.0.2.240"


def test_rediscover_none_when_no_agate(monkeypatch):
    s = Settings(fwh_host="192.0.2.110")
    monkeypatch.setattr(client.discover, "expand_targets", lambda subnet: ["x"])
    monkeypatch.setattr(client.discover, "scan", lambda *a, **k: [])
    assert client.rediscover(s, "192.0.2.110", "SN-KNOWN") is None
