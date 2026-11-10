#!/usr/bin/env python3
"""Fail if tracked files contain personal or site-identifying data.

Checks every file git would commit (tracked plus untracked-but-not-ignored) for:

- home-directory paths (macOS, Linux, Windows)
- FranklinWH aGate serial numbers (20 chars: 8 digits, letter, 2 digits, letter, 8 digits)
- MAC addresses other than the RFC 7042 documentation range
- IPv4 addresses, only when ``--ips`` is passed. Off by default: the owner does not treat
  LAN addresses as sensitive, and flagging every one of them buries the findings that matter
- email addresses other than noreply and example domains
- any term in the local, gitignored ``.pii-denylist`` (one per line, case-insensitive),
  plus terms in the ``PII_DENYLIST`` environment variable (comma-separated, for CI secrets)

The denylist lives outside git so the things it blocks (for example a real name) are never
committed. A line can opt out with the marker ``pii: allow``; use it sparingly and only for
placeholders the patterns misjudge.

Exit status: 0 clean, 1 findings.
"""

from __future__ import annotations

import ipaddress
import os
import re
import subprocess
import sys
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

ALLOW_MARKER = "pii: allow"
DENYLIST_FILE = ".pii-denylist"

# The lookbehind stops prose like "solar/home/grid" matching: a real path starts at a
# line break, whitespace, a quote or a bracket, never mid-word or mid-path.
HOME_PATH = re.compile(r"(?<![\w/])(?:/Users/|/home/|[A-Za-z]:\\Users\\)[A-Za-z0-9._-]+")
SERIAL = re.compile(r"\b\d{8}[A-Z]\d{2}[A-Z]\d{8}\b")
MAC = re.compile(r"\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b")
IPV4 = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

DOC_NETWORKS = tuple(
    ipaddress.ip_network(n)
    for n in ("192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24", "127.0.0.0/8", "0.0.0.0/32")
)
DOC_MAC_PREFIX = "00:00:5e:00:53"
#: Packaging manifests are expected to carry a maintainer address; it is published on the
#: package index anyway, so flagging it there is noise rather than a leak.
PACKAGING_FILES = frozenset({
    "pyproject.toml", "setup.cfg", "setup.py", "package.json",
    "build.yaml", "config.yaml", "repository.json",
})
ALLOWED_EMAIL_SUFFIXES = (
    "@users.noreply.github.com",
    "@noreply.anthropic.com",
    "@example.com",
    "@example.org",
    "@example.net",
    "@github.com",
)


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    kind: str
    text: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.kind}: {self.text}"


def _ip_allowed(text: str) -> bool:
    try:
        ip = ipaddress.ip_address(text)
    except ValueError:
        return True  # not an address (e.g. 999.1.1.1): not our concern
    return any(ip in net for net in DOC_NETWORKS)


def scan_text(path: str, text: str, denylist: Iterable[str] = (),
              *, check_ips: bool = False) -> Iterator[Finding]:
    packaging = Path(path).name in PACKAGING_FILES
    terms = [t.lower() for t in denylist if t]
    for lineno, line in enumerate(text.splitlines(), start=1):
        if ALLOW_MARKER in line:
            continue
        for m in HOME_PATH.finditer(line):
            yield Finding(path, lineno, "home path", m.group())
        for m in SERIAL.finditer(line):
            yield Finding(path, lineno, "serial number", m.group())
        for m in MAC.finditer(line):
            if not m.group().lower().replace("-", ":").startswith(DOC_MAC_PREFIX):
                yield Finding(path, lineno, "MAC address", m.group())
        if check_ips:
            for m in IPV4.finditer(line):
                if not _ip_allowed(m.group()):
                    yield Finding(path, lineno, "IP address", m.group())
        for m in EMAIL.finditer(line):
            if not packaging and not m.group().lower().endswith(ALLOWED_EMAIL_SUFFIXES):
                yield Finding(path, lineno, "email", m.group())
        lowered = line.lower()
        for term in terms:
            if term in lowered:
                yield Finding(path, lineno, "denylisted term", "<redacted>")


def load_denylist(root: Path) -> list[str]:
    terms: list[str] = []
    f = root / DENYLIST_FILE
    if f.is_file():
        for raw in f.read_text(encoding="utf-8").splitlines():
            term = raw.strip()
            if term and not term.startswith("#"):
                terms.append(term)
    terms += [t.strip() for t in os.environ.get("PII_DENYLIST", "").split(",") if t.strip()]
    return terms


def candidate_files(root: Path) -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=root,
        check=True,
        capture_output=True,
    ).stdout
    return [root / p for p in out.decode().split("\0") if p]


def main(argv: list[str] | None = None) -> int:
    args = list(argv or [])
    check_ips = "--ips" in args
    args = [a for a in args if a != "--ips"]
    root = Path(args[0]) if args else Path.cwd()
    denylist = load_denylist(root)
    findings: list[Finding] = []
    for file in candidate_files(root):
        if not file.is_file():
            continue  # deleted in the working tree
        try:
            text = file.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue  # binary; images need a manual check
        findings.extend(scan_text(str(file.relative_to(root)), text, denylist,
                                  check_ips=check_ips))
    for f in findings:
        print(f)
    if findings:
        print(
            f"\npii_check: {len(findings)} finding(s). Replace with placeholders "
            "(FWH-SN-REDACTED, 00:00:5E:00:53:00; 192.0.2.10 with --ips).",
            file=sys.stderr,
        )
        return 1
    print(f"pii_check: clean ({'with' if denylist else 'no'} denylist)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
