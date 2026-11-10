#!/bin/bash
# Demo / no-hardware mode: two seeded mock aGates + a bridge, all in Docker, isolated
# from the real setup (own port 8102, own ./data-demo volume, MQTT off). Nothing here
# touches the real container on 8101.
#
#   tools/demo.sh          build the image and bring the demo stack up
#   tools/demo.sh --down   tear the demo stack down
set -euo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
# -p keeps the demo in its own project namespace, fully separate from the real stack.
COMPOSE="docker compose -p fwh-demo -f $HERE/docker-compose.demo.yml"

if [[ "${1:-}" == "--down" ]]; then
  echo "==> tearing down demo stack"
  $COMPOSE down
  exit 0
fi

echo "==> building bridge image (rebuilds the franklinwh-direct-connect-api wheel)"
"$HERE/tools/build_image.sh"

echo "==> starting demo stack"
$COMPOSE up -d

echo
echo "Demo UI: http://localhost:8102"
echo "  (2 seeded mock aGates + bridge — live-looking data, no hardware)"
echo "  tear down with: tools/demo.sh --down"
