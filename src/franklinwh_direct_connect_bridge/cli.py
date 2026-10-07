"""Entrypoint: `franklinwh-direct-connect-bridge run` → serve the FastAPI app via uvicorn."""

from __future__ import annotations

import argparse
import logging

import uvicorn

from .config import get_settings


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="franklinwh-direct-connect-bridge")
    p.add_argument("command", nargs="?", default="run", choices=["run"])
    p.parse_args(argv)

    s = get_settings()
    logging.basicConfig(
        level=getattr(logging, s.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    uvicorn.run("franklinwh_direct_connect_bridge.app:create_app", factory=True,
                host=s.http_host, port=s.http_port, log_level=s.log_level)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
