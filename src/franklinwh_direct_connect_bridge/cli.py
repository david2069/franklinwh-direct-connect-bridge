"""Entrypoint: `franklinwh-direct-connect-bridge run` → serve the FastAPI app via uvicorn."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import getpass
import logging
import os
import socket
from pathlib import Path

import uvicorn

from . import config, environment, tls
from .config import get_settings

log = logging.getLogger(__name__)


def main(argv: list[str] | None = None, *, ask=input, ask_secret=getpass.getpass) -> int:
    p = argparse.ArgumentParser(prog="franklinwh-direct-connect-bridge")
    p.add_argument("command", nargs="?", default="run",
                   choices=["run", "setup", "ping", "reset-password"])
    p.add_argument("host", nargs="?", help="ping: the aGate's address (default: FWH_HOST); "
                                           "reset-password: the account's username")
    a = p.parse_args(argv)
    if a.command == "ping":
        return _ping(a.host or get_settings().fwh_host)
    if a.command == "reset-password":
        return _reset_password(a.host)
    if a.command == "setup":
        rc = _setup(ask, ask_secret)
        # Docker's `compose run` publishes no ports, so there it is started with `up -d`.
        if rc or environment.RUNTIME == "docker" or not _yes(ask, "Start the bridge now?", "y"):
            return rc
        config._settings = None     # read what setup just saved

    s = get_settings()
    logging.basicConfig(
        level=getattr(logging, s.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    quiet_transport_loggers()
    try:
        first_start_banner(s)
    except Exception as e:  # noqa: BLE001 — the banner must never stop the bridge starting
        log.warning("startup banner not shown: %s", e)
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


def _addresses(s, port: int, scheme: str) -> list[str]:
    """Addresses a browser can open. Uvicorn prints the one it listens on, 0.0.0.0 (every
    interface), which is not one."""
    if s.http_host not in ("0.0.0.0", "::", ""):
        return [f"{scheme}://{s.http_host}:{port}"]
    urls = [f"{scheme}://localhost:{port}"]
    if environment.RUNTIME == "docker":
        urls.append(f"{scheme}://<this computer's address>:{port} from another device")
        return urls
    with contextlib.suppress(OSError):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as so:
            so.connect(("192.0.2.1", 9))   # UDP: picks the outgoing interface, sends nothing
            urls.append(f"{scheme}://{so.getsockname()[0]}:{port} from another device")
    return urls


def first_start_banner(s) -> None:
    """Docker and pip: before the web server starts, where to open the bridge, whether it
    asks to sign in, and the first admin's password on the one start that generates it."""
    from . import __version__, auth, db, security
    if not environment.account_feature("startup_banner"):
        return
    store = db.get_store(s)
    shown: list[str] = []
    on = False
    if store is not None:
        security.decide_install(store, quick_start=s.security_quick_start)
        auth.ensure_tables(store)
        auth.ensure_first_admin(store, s, security_on=security.enabled(store),
                                reveal=shown.append)
        on = security.enabled(store)
    https = on and s.https_port
    urls = _addresses(s, s.https_port if https else s.http_port, "https" if https else "http")
    out = ["", "-" * 64, f"FranklinWH Direct Connect Bridge {__version__}",
           f"  Open:      {urls[0]}"] + [f"             {u}" for u in urls[1:]]
    if on:
        out.append("  Security: on: sign in" + (" (the browser warns once about the bridge's "
                                                "own certificate)" if https else ""))
        if shown:
            out += [f"  First admin: Username: admin  Password: {shown[0]}",
                    "               shown once; change it under Settings → Admin → Security"]
        else:
            out.append("  Sign in with your admin account. Lost the password? "
                       "franklinwh-direct-connect-bridge reset-password <username>")
    else:
        out.append("  Security: off: no sign-in. Turn it on under Settings → Admin → Security,"
                   " or run: franklinwh-direct-connect-bridge setup")
    f = config.settings_file()
    out += [f"  Settings:  {f}" if f.is_file() else
            "  Settings:  environment variables (franklinwh-direct-connect-bridge setup "
            "saves them for you)", "-" * 64, ""]
    print("\n".join(out), flush=True)


def _probe_line(host: str) -> str:
    from .diagnostics import probe
    r = probe(host)
    return (f"  {host}: Direct Connect port {r['port']} answered" if r["dc_9000"] else
            f"  {host}: no answer on the Direct Connect port {r['port']}; check the address, "
            "and that Direct Connect is on in the FranklinWH app")


#: What ``setup`` saves to the settings file; anything else in it is kept as written.
SETUP_KEYS = ("FWH_HOST", "HTTP_PORT", "HTTPS_PORT")


def _save_settings_file(values: dict[str, str]) -> None:
    f = config.settings_file()
    lines = f.read_text().splitlines() if f.is_file() else [
        "# Saved by franklinwh-direct-connect-bridge setup. Edit it, or run setup again;",
        "# environment variables win over it."]
    keys = {ln.split("=", 1)[0].strip() for ln in lines if "=" in ln}
    lines = [f"{ln.split('=', 1)[0].strip()}={values[ln.split('=', 1)[0].strip()]}"
             if "=" in ln and ln.split("=", 1)[0].strip() in values else ln for ln in lines]
    lines += [f"{k}={v}" for k, v in values.items() if k not in keys]
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("\n".join(lines) + "\n")
    with contextlib.suppress(OSError):
        os.chmod(f, 0o600)


def _yes(ask, prompt: str, default: str) -> bool:
    return (ask(f"{prompt} y/n [{default}]: ").strip() or default).lower().startswith("y")


def _setup(ask, ask_secret) -> int:
    """`franklinwh-direct-connect-bridge setup` (Docker and pip): the aGate's address, the
    ports, Security on or off and, optionally, the first admin, so a plain start needs no
    variables. Run it with the bridge stopped. Every question has a default, and all of it
    can be changed later. The password goes into the bridge's accounts, never a file."""
    from . import auth, db, security
    if not environment.account_feature("setup_command"):
        print("The add-on is set up from Home Assistant, not this command.")
        return 2
    data = Path(environment.DATA_DIR)
    if (not data.is_absolute() and Path.cwd().name == "data" and not data.exists()
            and not _yes(ask, f"No bridge data in {data.resolve()} yet. You are inside a "
                              "folder named data, which is probably the bridge's own. "
                              "Start a new install here?", "n")):
        print(f"Nothing changed ({data.resolve()} not made). Run setup from the folder that "
              "holds data: cd .. then franklinwh-direct-connect-bridge setup")
        return 1
    s = config.load_settings()

    def q(prompt: str, default) -> str:
        return ask(f"{prompt} [{default}]: ").strip() or str(default)

    print("FranklinWH Direct Connect Bridge setup\n"
          "Press Enter to accept the default in [brackets], or type your own. All of it\n"
          f"can be changed later: run setup again, or in the web UI. Data: {data.resolve()}\n")
    print("1. The aGate. Optional: leave it blank to add it later in the web UI.")
    host = q("   aGate address (IP or hostname)", s.fwh_host or "none")
    host = "" if host == "none" else host
    if host:
        print(" " + _probe_line(host))
    print("2. Ports. Keep the defaults unless something else on this computer uses them.")
    http_port = q("   Web port (HTTP)", s.http_port)
    https_port = q("   HTTPS port, 0 = off", s.https_port)
    print("3. Security. y: the web UI asks for a username and password (recommended).\n"
          "   n: anyone on your network can open it; turn it on later in Settings.")
    on = _yes(ask, "   Ask to sign in?", "y")
    if on and https_port.strip() == "0":
        https_port = "8102"
        print("   Security signs in over HTTPS only, so the HTTPS port stays on: 8102.")
    _save_settings_file({"FWH_HOST": host, "HTTP_PORT": http_port, "HTTPS_PORT": https_port})

    store = db.get_store(s)
    if store is None:
        print("No settings store, so Security and accounts can't be set.")
        return 1
    if store.get_config("security_install") in ("upgrade", "new"):
        security.set_enabled(store, on)
    else:
        security.decide_install(store, quick_start=not on)
    auth.ensure_tables(store)
    if on and not auth.has_admin(store):
        print("4. The admin account. Optional: skip it and the first start makes one,\n"
              "   username admin, and shows its password once in the terminal.")
        if _yes(ask, "   Choose the admin's username and password now?", "n"):
            name = q("   Admin username", "admin")
            pw = ask_secret("   Admin password (Enter = generate one): ")
            generated = not pw
            if generated:
                import secrets
                pw = secrets.token_urlsafe(12)
            elif ask_secret("   Again: ") != pw:
                print("The passwords differ; nothing changed. Run setup again.")
                return 1
            try:
                auth.create_user(store, name, pw, "admin")
            except auth.AuthError as e:
                print(f"Admin not made: {e}. Run setup again.")
                return 1
            print(f"   Admin made. Username: {name}" +
                  (f"  Password: {pw}  (shown once; change it under Settings → Admin → "
                   "Security)" if generated else ""))
    print(f"\nDone. aGate: {host or 'not set (add it in the web UI)'}  Web: {http_port}"
          f"  HTTPS: {https_port}  Security: {'on' if on else 'off'}\n"
          f"Saved to {config.settings_file().resolve()}.\n"
          "To start it later: franklinwh-direct-connect-bridge")
    return 0


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
