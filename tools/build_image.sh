#!/bin/bash
# Build the franklinwh-local-bridge Docker image. Builds the franklinwh-direct-connect-api wheel
# from the sibling repo and drops it in ./wheels/ so the image installs it auth-free
# (the library isn't on PyPI while private). Usage: tools/build_image.sh [tag]
set -euo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
LIB="${FWH_LOCAL_API_SRC:-$HERE/../franklinwh-local}"
CLOUD_LIB="${FWH_CLOUD_SRC:-$HERE/../franklinwh-cloud}"   # HYBRID Phase 3 reserve writes
TAG="${1:-franklinwh-local-bridge:dev}"

echo "==> building bundled wheels"
rm -rf "$HERE/wheels"; mkdir -p "$HERE/wheels"
# Prefer the repo venv's python — the system python3 is often "externally managed" (PEP 668)
# and refuses `pip install build`, which used to abort the whole build silently.
PY="python3"
[ -x "$HERE/.venv/bin/python" ] && PY="$HERE/.venv/bin/python"
"$PY" -c "import build" 2>/dev/null || "$PY" -m pip install --quiet --upgrade build
echo "  - franklinwh-direct-connect-api  <- $LIB"
( cd "$LIB" && "$PY" -m build --wheel --outdir "$HERE/wheels" ) >/dev/null
# franklinwh-cloud: needed at RUNTIME by the cloud reserve provider (updateSocV2). Optional —
# skip cleanly if the sibling repo isn't present (reserve writes just stay unavailable).
if [ -f "$CLOUD_LIB/pyproject.toml" ]; then
  echo "  - franklinwh-cloud      <- $CLOUD_LIB"
  ( cd "$CLOUD_LIB" && "$PY" -m build --wheel --outdir "$HERE/wheels" ) >/dev/null
else
  echo "  - franklinwh-cloud      SKIPPED (not found at $CLOUD_LIB)"
fi
ls -1 "$HERE/wheels"/*.whl

echo "==> building library docs (mkdocs)"
rm -rf "$HERE/docs_site"; mkdir -p "$HERE/docs_site"
# Build with the library's own venv (that's where mkdocs-material lives), falling back
# to the bridge venv. Degrades cleanly to an empty site (/guide just 404s) if unavailable.
DOCSPY="$PY"; [ -x "$LIB/.venv/bin/python" ] && DOCSPY="$LIB/.venv/bin/python"
if [ -f "$LIB/mkdocs.yml" ] && "$DOCSPY" -c "import mkdocs" 2>/dev/null; then
  ( cd "$LIB" && "$DOCSPY" -m mkdocs build --site-dir "$HERE/docs_site" ) >/dev/null && echo "  - docs built  <- $LIB"
else
  echo "  - docs SKIPPED (mkdocs not available; run: (cd $LIB && pip install mkdocs-material 'mkdocstrings[python]'))"
fi
touch "$HERE/docs_site/.gitkeep"

echo "==> docker build $TAG"
docker build -t "$TAG" "$HERE"
echo "==> done: $TAG"
