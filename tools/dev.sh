#!/bin/bash
# Rebuild the image, restart the container, and PROVE the container is running this
# working tree. Use this, not `docker compose up --build`.
#
# Why this exists: docker-compose.yml has no `build:` section, because the image needs
# sibling wheels built first and a bare `docker compose build` would produce a broken
# one. The consequence is that `docker compose up -d --build` silently does NOTHING
# and leaves the OLD container running — a live test then measures old code and
# "passes". That happened on 2026-10-14 and nearly shipped a fix that was not running.
#
# Usage: tools/dev.sh [--no-build]   (--no-build just restarts and re-checks)
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HERE"

WANT="$(tools/source_stamp.sh)"

if [ "${1:-}" != "--no-build" ]; then
  tools/build_image.sh
fi
docker compose up -d --force-recreate

PORT="${BRIDGE_PORT:-8101}"
for _ in $(seq 1 30); do
  RUNNING="$(curl -fsS --max-time 3 "http://127.0.0.1:$PORT/api/version" 2>/dev/null \
            | python3 -c 'import sys,json;print(json.load(sys.stdin).get("source_sha","unknown"))' 2>/dev/null || true)"
  [ -n "${RUNNING:-}" ] && break
  sleep 1
done

echo "working tree: $WANT"
echo "container   : ${RUNNING:-<no answer>}"

if [ "${RUNNING:-}" != "$WANT" ]; then
  echo "MISMATCH — the container is NOT running this working tree. Do not trust a live test." >&2
  exit 1
fi
case "$WANT" in
  *+*)     echo "OK (uncommitted changes are in the image; commit before quoting the SHA as evidence)" ;;
  *)       echo "OK" ;;
esac
