#!/bin/bash
# One definition of "which source is this?", shared by the image build and the check that
# the running container matches. Prints <short-sha> when the tree is clean, and
# <short-sha>+<8 hex of the diff> when it is not.
#
# The diff hash matters: a plain "-dirty" marker is identical before and after an edit, so
# it cannot catch "you changed a file and forgot to rebuild" — which is the mistake this
# whole mechanism exists to catch.
set -euo pipefail
cd "$(cd "$(dirname "$0")/.." && pwd)"
SHA="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
DIFF="$(git diff HEAD 2>/dev/null; git ls-files --others --exclude-standard 2>/dev/null | xargs -I{} shasum {} 2>/dev/null || true)"
if [ -n "$DIFF" ]; then
  printf '%s+%s\n' "$SHA" "$(printf '%s' "$DIFF" | shasum | cut -c1-8)"
else
  printf '%s\n' "$SHA"
fi
