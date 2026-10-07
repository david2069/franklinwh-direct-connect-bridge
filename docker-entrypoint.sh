#!/bin/sh
set -e

# Dev override: if the franklinwh-local library is mounted, install it editable so local
# changes take effect without a rebuild (mirrors energipays-bridge's client mount).
if [ -d /franklinwh-local ]; then
    pip install --no-cache-dir -e /franklinwh-local >/dev/null 2>&1 || true
fi

# HA Add-on mode: convert /data/options.json → env vars for pydantic-settings.
if [ -f /data/options.json ]; then
    python3 /app/src/franklinwh_direct_connect_bridge/ha_options.py /data/options.json /data/ha_options.env
    set -a
    . /data/ha_options.env
    set +a
fi

exec "$@"
