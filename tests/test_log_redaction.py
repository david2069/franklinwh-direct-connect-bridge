"""Debug logs must not carry the FranklinWH cloud loginToken or the gateway serial.

Measured on the HAOS test VM, 2026-10-23, franklinwh-cloud 0.6.1, bridge at DEBUG:
hpack and httpcore logged the request headers in clear (`logintoken` on 5 lines, the
cookie on 2), and httpx logged every request URL at INFO with `gatewayId=<serial>`.
"""
import logging

from franklinwh_direct_connect_bridge import cli


def _run_main_at(level, monkeypatch):
    async def _no_serve(s):
        return None
    monkeypatch.setattr(cli, "serve", _no_serve)
    s = cli.get_settings()
    monkeypatch.setattr(s, "log_level", level)
    for name in cli.TRANSPORT_LOGGERS:
        monkeypatch.setattr(logging.getLogger(name), "level", logging.NOTSET)
    # basicConfig does nothing once the root logger has handlers (pytest adds them), so
    # put the root where the add-on's basicConfig puts it.
    monkeypatch.setattr(logging.getLogger(), "level", getattr(logging, level.upper()))
    cli.main(["run"])
    logging.Logger.manager._clear_cache()


def test_debug_does_not_reach_the_http_client_loggers(monkeypatch):
    _run_main_at("debug", monkeypatch)
    for name in ("httpx", "httpcore", "hpack", "hpack.hpack", "httpcore.http2"):
        lg = logging.getLogger(name)
        assert not lg.isEnabledFor(logging.DEBUG), f"{name} would log headers at DEBUG"
        assert not lg.isEnabledFor(logging.INFO), f"{name} would log URLs (serial) at INFO"


def test_their_warnings_still_show(monkeypatch):
    _run_main_at("debug", monkeypatch)
    assert logging.getLogger("httpx").isEnabledFor(logging.WARNING)
