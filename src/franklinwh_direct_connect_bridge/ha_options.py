"""Convert a Home Assistant add-on options file (/data/options.json) to an env file
that pydantic-settings picks up. Called by docker-entrypoint.sh in add-on mode.

Usage: python ha_options.py /data/options.json /data/ha_options.env
"""

from __future__ import annotations

import json
import sys


def convert(options_path: str, env_path: str) -> None:
    with open(options_path) as f:
        opts = json.load(f)
    lines = []
    for key, val in opts.items():
        if isinstance(val, bool):
            val = "true" if val else "false"
        lines.append(f"{key.upper()}={val}")
    with open(env_path, "w") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    convert(sys.argv[1], sys.argv[2])
