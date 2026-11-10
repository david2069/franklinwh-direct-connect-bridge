"""#379 — every route that acts on an aGate names it. No gateway ⇒ 400, a malformed one
⇒ 422, an unknown one ⇒ 404, each before any device I/O. There is no default gateway."""
import inspect
import socket

import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import app as app_module, client, state

_APP = app_module.create_app()


def _uses(route, dep_name):
    stack = list(getattr(route, "dependant", None).dependencies) if getattr(route, "dependant", None) else []
    while stack:
        d = stack.pop()
        if getattr(d.call, "__name__", "") == dep_name:
            return True
        stack.extend(d.dependencies)
    return False


def _required_routes():
    out = []
    for r in _APP.routes:
        if not _uses(r, "_gateway_q"):
            continue
        path = r.path.replace("{", "").replace("}", "")      # any path parameter: a dummy
        for m in sorted(r.methods - {"HEAD"}):
            out.append((m, path))
    return sorted(set(out))


ROUTES = _required_routes()


def test_the_strict_dependency_covers_the_device_routes():
    assert len(ROUTES) >= 75
    paths = {p for _, p in ROUTES}
    for p in ("/api/summary", "/api/power", "/api/mode", "/api/battery/command", "/api/grid",
              "/api/metrics", "/api/billing/overview", "/api/health/link", "/api/cloud/reserve"):
        assert p in paths, p


@pytest.fixture
def no_io(monkeypatch):
    """Any connection attempt fails the test: every refusal comes before device I/O."""
    tried = []

    def refuse(self, addr, *a, **k):
        tried.append(addr)
        raise AssertionError(f"connection attempted to {addr}")
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(client, "writes_enabled", lambda s: True)
    gw = state.register_gateway("gw379", "192.0.2.79", "Real")
    gw.serial, gw.serial_locked = "SN379LOCKED", True
    yield tried
    state.unregister_gateway("gw379")


def _call(c, method, path, gw):
    url = path + ("" if gw is None else f"?gateway={gw}")
    return c.request(method, url, json={})


@pytest.mark.parametrize("method,path", ROUTES)
def test_missing_gateway_is_400(no_io, method, path):
    c = TestClient(_APP)
    r = _call(c, method, path, None)
    assert r.status_code == 400, (method, path, r.status_code, r.text[:200])
    assert "gateway is required" in r.json()["detail"]
    assert no_io == []


@pytest.mark.parametrize("method,path", ROUTES)
def test_unknown_gateway_is_404(no_io, method, path):
    r = _call(TestClient(_APP), method, path, "SN-NOT-HERE")
    assert r.status_code == 404, (method, path, r.status_code, r.text[:200])
    assert no_io == []


@pytest.mark.parametrize("method,path", ROUTES)
def test_malformed_gateway_is_422(no_io, method, path):
    r = _call(TestClient(_APP), method, path, "bad%20id%3B")
    assert r.status_code == 422, (method, path, r.status_code, r.text[:200])
    assert "not a gateway id or aGate serial" in str(r.json()["detail"])
    assert no_io == []


def test_a_locked_serial_names_the_gateway_and_an_unlocked_one_does_not(no_io):
    c = TestClient(_APP)
    # /api/health/link reads only recorded history: no device I/O either way.
    assert c.get("/api/health/link?gateway=SN379LOCKED").status_code == 200
    assert c.get("/api/health/link?gateway=sn379locked").status_code == 200
    other = state.register_gateway("gw380", "192.0.2.80", "Unlocked")
    other.serial = "SN380SEEN"                    # reported but never locked (#381)
    try:
        assert c.get("/api/health/link?gateway=SN380SEEN").status_code == 404
    finally:
        state.unregister_gateway("gw380")


def test_the_resolver_never_falls_back_to_the_default():
    src = inspect.getsource(app_module.create_app)
    body = src[src.index("    def _gw_or_404("):]
    body = body[:body.index("\n    def _gateway_q(")]
    assert "get_state()" not in body and "default_gateway()" not in body


def test_dispatch_requires_its_gateway(no_io):
    r = TestClient(_APP).post("/api/dispatch", json={"action": "discharge", "power_w": 1000})
    assert r.status_code == 400 and no_io == []
