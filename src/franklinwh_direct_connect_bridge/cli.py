"""Entrypoint: `franklinwh-direct-connect-bridge run` → serve the FastAPI app via uvicorn."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging

import uvicorn

from . import tls
from .config import get_settings

log = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="franklinwh-direct-connect-bridge")
    p.add_argument("command", nargs="?", default="run", choices=["run", "ping", "reset-password"])
    p.add_argument("host", nargs="?", help="ping: the aGate's address (default: FWH_HOST); "
                                           "reset-password: the account's username")
    a = p.parse_args(argv)
    if a.command == "ping":
        return _ping(a.host or get_settings().fwh_host)
    if a.command == "reset-password":
        return _reset_password(a.host)

    s = get_settings()
    logging.basicConfig(
        level=getattr(logging, s.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    quiet_transport_loggers()
    asyncio.run(serve(s))
    return 0


async def serve(s) -> None:
    """Port 8101 (HTTP) and the HTTPS port, one app. HTTP runs the app's start-up and owns
    Ctrl-C/SIGTERM; HTTPS shares the running app. If HTTPS can't start (a bad certificate,
    the port taken), HTTP carries on and Settings → Admin → Security says why."""
    from .app import create_app
    app = create_app()
    http = uvicorn.Server(uvicorn.Config(app, host=s.http_host, port=s.http_port,
                                         log_level=s.log_level))
    https = https_server(app, s)
    task = asyncio.create_task(run_https(https)) if https is not None else None
    try:
        await http.serve()
    finally:
        if task is not None:
            https.should_exit = True
            with contextlib.suppress(BaseException):
                await task


class _SharedSignals(uvicorn.Server):
    """The HTTPS server: leaves the signals to the HTTP server, which stops it."""

    @contextlib.contextmanager
    def capture_signals(self):
        yield


def https_server(app, s):
    """The HTTPS server, or None when it is off or its certificate can't be had."""
    tls.status.update(port=s.https_port, running=False, error="", source="", certfile="")
    tls.server = None
    if not s.https_port:
        return None
    try:
        cert, key, source = tls.ensure_cert(s)
    except Exception as e:  # noqa: BLE001 — HTTPS failing must never stop HTTP
        tls.status["error"] = str(e)
        log.error("HTTPS port %s not started: %s", s.https_port, e)
        return None
    tls.status.update(source=source, certfile=cert)
    tls.server = _SharedSignals(uvicorn.Config(
        app, host=s.http_host, port=s.https_port, log_level=s.log_level, lifespan="off",
        ssl_certfile=cert, ssl_keyfile=key))
    return tls.server


async def run_https(server) -> None:
    try:
        await server.serve()
    except BaseException as e:  # noqa: BLE001 — uvicorn exits on a failed bind
        tls.status["error"] = (f"could not listen on port {server.config.port}"
                               if isinstance(e, SystemExit) else str(e))
        log.error("HTTPS port %s stopped: %s", server.config.port, tls.status["error"])


#: The HTTP client's own loggers. At DEBUG, hpack and httpcore print every request header
#: in clear — the FranklinWH cloud loginToken and cookie among them — and httpx logs each
#: request URL at INFO, the gateway serial included. The bridge's log level must never
#: reach them: DEBUG is what a user turns on to send us a log.
TRANSPORT_LOGGERS = ("httpx", "httpcore", "hpack")


def quiet_transport_loggers() -> None:
    for name in TRANSPORT_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)


def _reset_password(username: str | None) -> int:
    """`franklinwh-direct-connect-bridge reset-password NAME` (#457): a new random password,
    printed once; the account is unlocked and enabled. A new name becomes an admin."""
    from . import auth, db
    if not username:
        print("no username: reset-password <name>")
        return 2
    store = db.get_store(get_settings())
    if store is None:
        print("no settings store (metrics are off), so there are no accounts")
        return 1
    auth.ensure_tables(store)
    try:
        pw = auth.reset_password(store, username)
    except auth.AuthError as e:
        print(f"not reset: {e}")
        return 1
    print(f"{username}: new password {pw}\n(shown once; sign in and change it)")
    return 0


def _ping(host: str) -> int:
    """`franklinwh-direct-connect-bridge ping [HOST]`: a timed ping and a timed connect to
    the Direct Connect port :9000 (#123). Never touches the aGate Modbus TCP Server :502."""
    from .diagnostics import probe
    if not host:
        print("no host: pass one, or set FWH_HOST")
        return 2
    r = probe(host)
    ping = f"ok {r['ping_ms']} ms" if r["ping"] else "no reply"
    dc = (f"ok {r['dc_9000_connect_ms']} ms" if r["dc_9000"] else "refused / timed out")
    print(f"{r['host']}\n  ping           {ping}\n  :{r['port']} connect  {dc}")
    return 0 if r["dc_9000"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
