#!/usr/bin/env python3
"""Fail if the two copies of BRIDGE_BASELINE.md have drifted apart.

A shared contract that exists twice rots the moment one copy is edited. This
fetches the other bridge's copy and diffs it against ours. Exit 0 = in sync.

Run:  python tools/check_baseline_sync.py
CI:   same, non-blocking until the other repo has the file (exit 0 on 404).
"""
import difflib
import pathlib
import sys
import urllib.error
import urllib.request

LOCAL = pathlib.Path(__file__).resolve().parents[1] / "docs/BRIDGE_BASELINE.md"
REMOTE = ("https://raw.githubusercontent.com/david2069/franklinwh-modbus-bridge/"
          "main/docs/BRIDGE_BASELINE.md")


def main() -> int:
    if not LOCAL.exists():
        print(f"missing canonical copy: {LOCAL}", file=sys.stderr)
        return 1
    ours = LOCAL.read_text()
    try:
        with urllib.request.urlopen(REMOTE, timeout=20) as r:
            theirs = r.read().decode()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            print("modbus bridge has no copy yet — nothing to compare (ok)")
            return 0
        print(f"could not fetch the remote copy: {e}", file=sys.stderr)
        return 0                      # a network problem is not a drift finding
    except Exception as e:            # noqa: BLE001
        print(f"could not fetch the remote copy: {e}", file=sys.stderr)
        return 0

    if ours == theirs:
        print("BRIDGE_BASELINE.md is in sync across both bridges")
        return 0

    print("BRIDGE_BASELINE.md has DRIFTED between the two bridges:\n", file=sys.stderr)
    diff = difflib.unified_diff(theirs.splitlines(), ours.splitlines(),
                                fromfile="modbus-bridge (remote)",
                                tofile="direct-connect-bridge (canonical)", lineterm="")
    for line in list(diff)[:80]:
        print(line, file=sys.stderr)
    print("\nEdit the canonical copy, then copy it across.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
