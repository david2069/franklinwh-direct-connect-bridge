"""#123 — link & load diagnostics: read-only, never opens :502, counts existing sockets."""
import socket

from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import app as app_module, cli, diagnostics, state

PROC = """  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode
   0: 0F02000A:A1B2 0A0200C0:2328 01 00000000:00000000 00:00000000 00000000     0        0 1
   1: 0F02000A:A1B3 0A0200C0:2328 06 00000000:00000000 00:00000000 00000000     0        0 2
   2: 0F02000A:A1B4 0A0200C0:01F6 01 00000000:00000000 00:00000000 00000000     0        0 3
   3: 0F02000A:A1B5 0B0200C0:2328 01 00000000:00000000 00:00000000 00000000     0        0 4
"""


def test_counts_this_bridges_sockets_by_port_and_state(tmp_path):
    f = tmp_path / "tcp"
    f.write_text(PROC)
    c = diagnostics.connections_to("192.0.2.10", str(f))      # 0A0200C0 = 192.0.2.10
    assert c["dc_9000"] == 2 and c["modbus_tcp_server_502"] == 1
    assert c["by_port"]["9000"] == {"ESTABLISHED": 1, "TIME_WAIT": 1}


def test_no_proc_means_unknown_not_zero(tmp_path):
    assert diagnostics.connections_to("192.0.2.10", str(tmp_path / "missing")) is None


def test_probe_never_opens_502(monkeypatch):
    opened = []
    monkeypatch.setattr(diagnostics.discover, "ping", lambda h, timeout=1.0: True)

    class _S:
        def __enter__(self): return self
        def __exit__(self, *a): return False
    monkeypatch.setattr(socket, "create_connection",
                        lambda addr, timeout=None: opened.append(addr[1]) or _S())
    r = diagnostics.probe("192.0.2.10:9000")
    assert r["ping"] and r["dc_9000"] and opened == [9000]


def test_endpoint_skips_mocks_and_reports_the_bridge(monkeypatch):
    state.reset_gateways()
    state.register_gateway("m1", "127.0.0.1:1", "mock", is_mock=True)
    monkeypatch.setattr(diagnostics, "probe", lambda h: {"ping": True})
    d = TestClient(app_module.create_app()).get("/api/diagnostics/link").json()
    assert d["gateways"][0]["is_mock"] and "ping" not in d["gateways"][0]
    assert "rss_mb" in d["bridge"] and "threads" in d["bridge"]
    state.reset_gateways()


def test_cli_ping(monkeypatch, capsys):
    monkeypatch.setattr(diagnostics, "probe", lambda h: {"host": "192.0.2.10", "ping": True,
                        "ping_ms": 3.1, "dc_9000": True, "dc_9000_connect_ms": 9.9})
    assert cli.main(["ping", "192.0.2.10"]) == 0
    out = capsys.readouterr().out
    assert "ping           ok 3.1 ms" in out and ":9000 connect  ok 9.9 ms" in out
