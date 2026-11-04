#!/usr/bin/env python3
"""Install smoke check (#409): does a fresh standalone install start, take a mock gateway,
poll it and, with MQTT, publish it? Run against a bridge that was just installed from this
checkout by Docker Compose or pip; the workflow (.github/workflows/install-smoke.yml) does
the installing. Follows the shared fwh-tools "install-smoke" spec, so the Modbus bridge's
copy differs only in BRIDGE below.

    install_smoke.py --base http://127.0.0.1:8101 [--mqtt 127.0.0.1:1883] \
        (--log bridge.log | --log-cmd "docker compose logs") --out smoke/ \
        [--https https://127.0.0.1:8102 --cacert data/tls/bridge.crt --user U --password P]

With --https (#457: a new install starts with Security on), the health check stays on
--base, which must send everything else to HTTPS; the gateway checks then run on the
HTTPS port, signed in, trusting only the bridge's own certificate.

Stdlib only, plus paho-mqtt for --mqtt. Exit 0 when every check passes. Mock gateway only:
it never connects to an aGate."""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from http.cookiejar import CookieJar

#: The only bridge-specific part.
BRIDGE = {
    "health": "/api/live",
    "add_gateway": ("POST", "/api/gateways", {"label": "smoke", "is_mock": True, "publish_ha": True}),
    "gateways": "/api/gateways",
    "discovery_prefix": "homeassistant",
}

#: Log lines that fail the run. A fresh install with defaults should log neither.
BAD_LOG = re.compile(r"\bERROR\b|Traceback \(most recent call last\)")


_opener = urllib.request.build_opener()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def use_https(cacert: str) -> None:
    """Later requests trust only ``cacert`` and keep the session cookie."""
    global _opener
    ctx = ssl.create_default_context(cafile=cacert)
    _opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx),
                                          urllib.request.HTTPCookieProcessor(CookieJar()))


def redirect_of(url: str, timeout=10) -> tuple[int, str]:
    """The status and Location of ``url``, without following it."""
    try:
        with urllib.request.build_opener(_NoRedirect).open(url, timeout=timeout) as r:
            return r.status, ""
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Location", "")


def http(base: str, method: str, path: str, body=None, timeout=10):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with _opener.open(req, timeout=timeout) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")[:500]


def bad_log_lines(text: str) -> list[str]:
    return [ln for ln in text.splitlines() if BAD_LOG.search(ln)]


def discovery_topics(topics, serial: str, prefix: str) -> list[str]:
    """Retained discovery config topics that belong to the gateway with ``serial``."""
    s8 = (serial or "")[-8:].lower()
    return sorted(t for t in topics
                  if s8 and t.startswith(prefix + "/") and t.endswith("/config") and s8 in t.lower())


def retained_topics(hostport: str, prefix: str, wait_s: float = 5.0) -> list[str]:
    import paho.mqtt.client as mqtt
    host, _, port = hostport.partition(":")
    got: set[str] = set()
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="install-smoke")
    c.on_message = lambda _c, _u, m: m.retain and m.payload and got.add(m.topic)
    c.connect(host, int(port or 1883))
    c.subscribe(prefix + "/#")
    c.loop_start()
    time.sleep(wait_s)
    c.loop_stop()
    c.disconnect()
    return sorted(got)


def secure(a, check, deadline) -> bool:
    """Security on: 8101 redirects to HTTPS; HTTPS answers with the bridge's own
    certificate, asks for a sign-in, and takes the admin's."""
    path = BRIDGE["gateways"]
    st, loc = redirect_of(a.base + path)
    if not check("8101 sends requests to the HTTPS port", st == 307 and loc == a.https + path,
                 f"HTTP {st} -> {loc}"):
        return False
    use_https(a.cacert)
    st, live = None, None
    while time.monotonic() < deadline:
        try:
            st, live = http(a.https, "GET", BRIDGE["health"], timeout=4)
            break
        except OSError as e:
            live = str(e)
            time.sleep(2)
    if not check("the HTTPS port answers with the bridge's own certificate", st == 200, f"HTTP {st} {live}"):
        return False
    st, _ = http(a.https, "GET", path)
    if not check("the HTTPS port asks for a sign-in", st == 401, f"HTTP {st}"):
        return False
    st, me = http(a.https, "POST", "/api/auth/login", {"username": a.user, "password": a.password})
    return check("the admin signs in", st == 200, f"HTTP {st} {me if st != 200 else ''}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--base", required=True)
    p.add_argument("--mqtt", default="", help="host:port of the broker the bridge publishes to")
    lg = p.add_mutually_exclusive_group(required=True)
    lg.add_argument("--log", help="the bridge's log file, read at the end")
    lg.add_argument("--log-cmd", help="a command that prints the bridge's log, run at the end")
    p.add_argument("--out", required=True)
    p.add_argument("--version", default="", help="the version under test; health must report it")
    p.add_argument("--timeout", type=float, default=180)
    p.add_argument("--https", default="", help="the HTTPS port's base URL (Security on)")
    p.add_argument("--cacert", default="", help="the bridge's own certificate, to trust")
    p.add_argument("--user", default="")
    p.add_argument("--password", default="")
    a = p.parse_args(argv)
    out = pathlib.Path(a.out)
    (out / "api").mkdir(parents=True, exist_ok=True)
    results: list[dict] = []

    def check(name, ok, detail=""):
        results.append({"check": name, "ok": bool(ok), "detail": str(detail)})
        print(("PASS " if ok else "FAIL ") + name + (f": {detail}" if detail else ""), flush=True)
        return ok

    def save(name, obj):
        (out / "api" / f"{name}.json").write_text(json.dumps(obj, indent=1, default=str))

    deadline = time.monotonic() + a.timeout
    st, live = None, None
    while time.monotonic() < deadline:
        try:
            st, live = http(a.base, "GET", BRIDGE["health"], timeout=4)
            if st == 200:
                break
        except OSError:
            pass
        time.sleep(2)
    save("live", live)
    got = (live or {}).get("version") if isinstance(live, dict) else None
    if check("the bridge answers its health check", st == 200 and (not a.version or got == a.version),
             f"HTTP {st}, version {got}" + (f" (want {a.version})" if a.version else "")) \
            and (not a.https or secure(a, check, deadline)):
        base = a.https or a.base
        method, path, body = BRIDGE["add_gateway"]
        st, gw = http(base, method, path, body, timeout=30)
        save("add-gateway", gw)
        check("a mock gateway can be added", st in (200, 201), f"HTTP {st} {gw if st >= 300 else ''}")

        mock = None
        while time.monotonic() < deadline:
            st, gws = http(base, "GET", BRIDGE["gateways"])
            mock = next((g for g in gws if g.get("is_mock")), None) if isinstance(gws, list) else None
            if mock and mock.get("ok"):
                break
            time.sleep(3)
        save("gateways", gws)
        check("the mock gateway polls", bool(mock and mock.get("ok")),
              "" if mock else "no mock gateway listed")

        if a.mqtt:
            topics = []
            while time.monotonic() < deadline:
                topics = retained_topics(a.mqtt, BRIDGE["discovery_prefix"])
                if discovery_topics(topics, (mock or {}).get("serial"), BRIDGE["discovery_prefix"]):
                    break
            ours = discovery_topics(topics, (mock or {}).get("serial"), BRIDGE["discovery_prefix"])
            save("retained-topics", topics)
            check("the mock gateway's discovery configs are retained on the broker", ours,
                  f"{len(ours)} of {len(topics)} retained topics")

    if a.log_cmd:
        log = subprocess.run(a.log_cmd, shell=True, capture_output=True, text=True).stdout
    else:
        f = pathlib.Path(a.log)
        log = f.read_text(errors="replace") if f.exists() else ""
    (out / "bridge.log").write_text(log)
    bad = bad_log_lines(log)
    check("the log was captured", bool(log), a.log or a.log_cmd)
    check("no ERROR or Traceback in the log", not bad, "; ".join(bad[:5]))

    passed = sum(r["ok"] for r in results)
    (out / "summary.json").write_text(json.dumps(
        {"base": a.base, "https": a.https or None, "mqtt": a.mqtt or None, "passed": passed,
         "total": len(results),
         "checks": results}, indent=1))
    print(f"RESULT: {passed}/{len(results)} checks passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
