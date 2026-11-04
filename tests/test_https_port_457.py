"""#457 phase 2: the HTTPS port (8102) next to 8101, with your own or a self-signed
certificate."""
import asyncio
import datetime as dt
import socket
import ssl
import types
import urllib.request

import pytest
from cryptography import x509

from franklinwh_direct_connect_bridge import cli, environment, tls


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setattr(environment, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(tls, "local_names", lambda: (["bridge", "localhost"], ["127.0.0.1", "192.0.2.5"]))
    return tmp_path


def _s(**kw):
    base = dict(ssl_certfile="", ssl_keyfile="", https_port=8102, http_host="127.0.0.1", log_level="info")
    return types.SimpleNamespace(**{**base, **kw})


def test_a_self_signed_certificate_is_made_once_and_kept(data):
    cert, key, source = tls.ensure_cert(_s())
    assert source == "self-signed" and cert.endswith("tls/bridge.crt")
    c = x509.load_pem_x509_certificate(open(cert, "rb").read())
    assert c.extensions.get_extension_for_class(x509.BasicConstraints).value.ca  # a phone can trust it
    days = (c.not_valid_after_utc - c.not_valid_before_utc).days
    assert 824 <= days <= 825                                                 # iOS's limit
    d = tls.describe(cert)
    assert d["names"] == ["bridge", "localhost", "127.0.0.1", "192.0.2.5"]
    assert len(d["fingerprint_sha256"].split(":")) == 32
    before = open(cert, "rb").read()
    tls.ensure_cert(_s())
    assert open(cert, "rb").read() == before                                  # kept


def test_it_is_made_again_near_expiry_or_when_the_address_changes(data, monkeypatch):
    cert, _, _ = tls.ensure_cert(_s())
    first = open(cert, "rb").read()
    tls.ensure_cert(_s(), now=dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=800))
    second = open(cert, "rb").read()
    assert second != first
    monkeypatch.setattr(tls, "local_names", lambda: (["bridge", "localhost"], ["127.0.0.1", "192.0.2.77"]))
    tls.ensure_cert(_s())
    assert open(cert, "rb").read() != second and "192.0.2.77" in tls.describe(cert)["names"]


def test_your_own_certificate_wins_and_must_exist(data, monkeypatch):
    own_c, own_k, _ = tls.ensure_cert(_s())
    assert tls.ensure_cert(_s(ssl_certfile=own_c, ssl_keyfile=own_k)) == (own_c, own_k, "own")
    with pytest.raises(ValueError, match="both"):
        tls.ensure_cert(_s(ssl_certfile=own_c))
    with pytest.raises(ValueError, match="does not exist"):
        tls.ensure_cert(_s(ssl_certfile="/nope.pem", ssl_keyfile=own_k))
    monkeypatch.setattr(environment, "IS_HA_ADDON", True)                     # bare name → /ssl
    with pytest.raises(ValueError, match="/ssl/fullchain.pem"):
        tls.ensure_cert(_s(ssl_certfile="fullchain.pem", ssl_keyfile="privkey.pem"))


def test_port_0_turns_it_off_and_a_bad_certificate_leaves_http_running(data):
    assert cli.https_server(object(), _s(https_port=0)) is None
    assert cli.https_server(object(), _s(ssl_certfile="/nope.pem", ssl_keyfile="/nope.key")) is None
    assert "does not exist" in tls.status["error"]


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_the_https_port_serves_the_app_over_tls(data):
    async def app(scope, receive, send):
        if scope["type"] != "http":
            return
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    port = _free_port()

    async def run():
        srv = cli.https_server(app, _s(https_port=port))
        task = asyncio.create_task(cli.run_https(srv))
        for _ in range(100):
            if srv.started:
                break
            await asyncio.sleep(0.05)
        assert tls.running()
        ctx = ssl.create_default_context(cafile=tls.status["certfile"])       # trusts the bridge's own
        body = await asyncio.to_thread(
            lambda: urllib.request.urlopen(f"https://localhost:{port}/", context=ctx, timeout=5).read())
        srv.should_exit = True
        await task
        return body

    assert asyncio.run(run()) == b"ok"
    assert not tls.running()


def test_a_taken_port_is_reported_not_fatal(data):
    port = _free_port()
    with socket.socket() as blocker:
        blocker.bind(("127.0.0.1", port))
        blocker.listen()
        srv = cli.https_server(object(), _s(https_port=port))
        asyncio.run(cli.run_https(srv))
    assert tls.status["error"] == f"could not listen on port {port}"


def test_settings_shows_the_https_port_and_offers_the_certificate(data, monkeypatch):
    from fastapi.testclient import TestClient
    from franklinwh_direct_connect_bridge import app as app_module, db
    from franklinwh_direct_connect_bridge.db import MetricsStore
    store = MetricsStore(str(data / "m.db"))
    monkeypatch.setattr(db, "get_store", lambda s: store)
    c = TestClient(app_module.create_app())
    assert cli.https_server(object(), _s(https_port=0)) is None               # off
    h = c.get("/api/security").json()["https"]
    assert h["port"] == 0 and not h["running"] and "fingerprint_sha256" not in h
    assert c.get("/api/security/certificate").status_code == 404
    cli.https_server(object(), _s())                                          # made, not started
    h = c.get("/api/security").json()["https"]
    assert h["source"] == "self-signed" and h["fingerprint_sha256"] and not h["running"]
    r = c.get("/api/security/certificate")
    assert r.status_code == 200 and r.content.startswith(b"-----BEGIN CERTIFICATE-----")
    assert "franklinwh-bridge.crt" in r.headers["content-disposition"]
    from pathlib import Path
    html = (Path(app_module.__file__).parent / "templates/tabs/settings.html").read_text()
    for s in ('data-testid="https-section"', 'data-testid="cert-fingerprint"', 'href="api/security/certificate"'):
        assert s in html, s
