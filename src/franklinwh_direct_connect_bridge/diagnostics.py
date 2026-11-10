"""Link and resource diagnostics (#123): is the aGate reachable, how many connections this
bridge holds to it, and what the bridge itself is using.

Owner, 2026-10-16: a live aGate stopped answering in windows and the question was whether
too many connections, or the container, were to blame. None of that could be measured.
Everything here is read-only and never opens the aGate Modbus TCP Server (:502); the
connection count is of sockets that already exist.
"""
from __future__ import annotations

import os
import socket
import time
from typing import Any

from franklinwh_direct_connect_api import discover

DC_PORT = discover.PORT_SENDMQTT          # Direct Connect, 9000
MODBUS_TCP_SERVER_PORT = 502              # aGate Modbus TCP Server (counted, never opened)

#: /proc/net/tcp state codes (include/net/tcp_states.h).
_TCP_STATES = {"01": "ESTABLISHED", "02": "SYN_SENT", "03": "SYN_RECV", "04": "FIN_WAIT1",
               "05": "FIN_WAIT2", "06": "TIME_WAIT", "07": "CLOSE", "08": "CLOSE_WAIT",
               "09": "LAST_ACK", "0A": "LISTEN", "0B": "CLOSING"}


def probe(host: str) -> dict[str, Any]:
    """ICMP ping and a TCP connect to :9000, each timed. Never touches :502."""
    h = host.split(":")[0]
    t0 = time.perf_counter()
    try:
        ping_ok = bool(discover.ping(h, timeout=1.0))
    except Exception:  # noqa: BLE001
        ping_ok = False
    ping_ms = round((time.perf_counter() - t0) * 1000, 1) if ping_ok else None
    t0 = time.perf_counter()
    try:
        with socket.create_connection((h, DC_PORT), timeout=3.0):
            pass
        connect_ms = round((time.perf_counter() - t0) * 1000, 1)
    except OSError:
        connect_ms = None
    return {"host": h, "ping": ping_ok, "ping_ms": ping_ms,
            "dc_9000": connect_ms is not None, "dc_9000_connect_ms": connect_ms}


def _hex_ip(ip: str) -> str | None:
    try:
        return socket.inet_aton(ip)[::-1].hex().upper()
    except OSError:
        return None


def connections_to(host: str, proc_tcp: str = "/proc/net/tcp") -> dict[str, Any] | None:
    """Count this network namespace's TCP sockets to ``host`` by remote port and state.
    In the add-on / Docker the namespace is the bridge's own container. None where
    /proc/net/tcp does not exist (macOS dev runs)."""
    want = _hex_ip(host.split(":")[0])
    if not want or not os.path.exists(proc_tcp):
        return None
    by_port: dict[int, dict[str, int]] = {}
    with open(proc_tcp) as f:
        next(f, None)
        for line in f:
            cols = line.split()
            if len(cols) < 4:
                continue
            rip, rport = cols[2].split(":")
            if rip != want:
                continue
            port = int(rport, 16)
            st = _TCP_STATES.get(cols[3], cols[3])
            by_port.setdefault(port, {})
            by_port[port][st] = by_port[port].get(st, 0) + 1
    def tot(p: int) -> int:
        return sum(by_port.get(p, {}).values())
    return {"dc_9000": tot(DC_PORT), "modbus_tcp_server_502": tot(MODBUS_TCP_SERVER_PORT),
            "by_port": {str(p): v for p, v in sorted(by_port.items())}}


_cpu_last: tuple[float, float] | None = None


def resources() -> dict[str, Any]:
    """The bridge process: CPU % since the previous call, RSS, threads, open files."""
    global _cpu_last
    out: dict[str, Any] = {"pid": os.getpid()}
    try:
        t = os.times()
        cpu = t.user + t.system
        now = time.monotonic()
        if _cpu_last is not None and now > _cpu_last[1]:
            out["cpu_pct"] = round((cpu - _cpu_last[0]) / (now - _cpu_last[1]) * 100, 1)
        else:
            out["cpu_pct"] = None
        _cpu_last = (cpu, now)
    except Exception:  # noqa: BLE001
        out["cpu_pct"] = None
    status = "/proc/self/status"
    if os.path.exists(status):
        with open(status) as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    out["rss_mb"] = round(int(line.split()[1]) / 1024, 1)
                elif line.startswith("Threads:"):
                    out["threads"] = int(line.split()[1])
        try:
            out["open_fds"] = len(os.listdir("/proc/self/fd"))
        except OSError:
            pass
    else:
        import resource, threading
        out["rss_mb"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024 / 1024, 1)
        out["threads"] = threading.active_count()
    return out
