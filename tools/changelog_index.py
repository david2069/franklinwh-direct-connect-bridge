#!/usr/bin/env python3
"""Keep CHANGELOG.md a short index over full per-version notes.

Layout (policy: docs/TEST_POLICY.md, "Changelog layout"):

* ``CHANGELOG.md``: the preamble, ``## [Unreleased]`` in full (the working area), then an
  index, newest first, grouped by release day.
* ``docs/changelog/<version>.md``: the full notes of one release, ``# <version> — <date>``
  followed by the section text exactly as it was written. Released notes are never edited.

Commands:

    changelog_index.py release X.Y.Z YYYY-MM-DD   move [Unreleased] out, add the index entry
    changelog_index.py migrate                    one-off: split a single-file CHANGELOG
    changelog_index.py rebuild                    regenerate the index and the docs nav
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = "https://david2069.github.io/franklinwh-direct-connect-bridge"

SECTION_RE = re.compile(r"^## \[(\d+\.\d+\.\d+)\] — (\d{4}-\d{2}-\d{2})\s*$", re.M)
UNRELEASED = "## [Unreleased]"
KIND_ORDER = ["Added", "Changed", "Fixed", "Removed"]
MAX_HIGHLIGHTS = 6
MAX_CLAUSE = 80
MAX_AREA = 90


def _vkey(version: str) -> tuple[int, ...]:
    return tuple(int(p) for p in version.split("."))


def _paths(root: Path) -> tuple[Path, Path, Path]:
    return root / "CHANGELOG.md", root / "docs" / "changelog", root / "mkdocs.yml"


# --- parsing -------------------------------------------------------------------------------

def split_changelog(text: str) -> tuple[str, str, list[tuple[str, str, str]]]:
    """Return (preamble, unreleased body, [(version, date, body)]) from a single-file changelog."""
    start = text.index(UNRELEASED)
    preamble = text[:start]
    matches = list(SECTION_RE.finditer(text))
    unreleased_end = matches[0].start() if matches else len(text)
    unreleased = text[start + len(UNRELEASED):unreleased_end]
    sections = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections.append((m.group(1), m.group(2), text[m.end():end]))
    return preamble, unreleased, sections


def tidy(body: str) -> str:
    """Strip only the blank lines around a section; the text itself is untouched."""
    return body.strip("\n") + "\n"


def doc_text(version: str, date: str, body: str) -> str:
    return f"# {version} — {date}\n\n{tidy(body)}"


def read_doc(path: Path) -> tuple[str, str, str]:
    text = path.read_text()
    m = re.match(r"# (\d+\.\d+\.\d+) — (\d{4}-\d{2}-\d{2})\n\n", text)
    if not m:
        raise SystemExit(f"{path}: first line must be '# <version> — <date>'")
    return m.group(1), m.group(2), text[m.end():]


def summarise(body: str) -> tuple[dict[str, int], list[str]]:
    """Counts per subsection name, and highlights (bold lead-ins, Added and Fixed first)."""
    lines = body.splitlines()
    counts: dict[str, int] = {}
    entries: dict[str, list[str]] = {}
    intro: list[str] = []
    current = None
    fence = False
    for line in lines:
        if line.startswith("```"):
            fence = not fence
        if fence:
            continue
        m = re.match(r"^### (.+?)\s*$", line)
        if m:
            current = m.group(1)
            counts.setdefault(current, 0)
            entries.setdefault(current, [])
            continue
        if line.startswith("- "):
            if current is None:
                intro.append(line)
            else:
                counts[current] += 1
                entries[current].append(line)
    # A grouped summary paragraph ("by area") replaces the entry lead-ins.
    area = [area_line(b) for b in intro]
    if area:
        return counts, area[:MAX_HIGHLIGHTS]
    order = ["Added", "Fixed"] + [k for k in entries if k not in ("Added", "Fixed")]
    picks = [lead(b) for k in order for b in entries.get(k, [])]
    return counts, picks[:MAX_HIGHLIGHTS]


def cut(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(",;:") + "…"


def area_line(bullet: str) -> str:
    """'- **Billing:** a; b.' -> 'Billing: a' (first clause, cut at MAX_AREA on a word boundary)."""
    text = bullet[2:].strip()
    m = re.match(r"\*\*(.+?)\*\*\s*(.*)", text)
    if not m:
        return lead(bullet)
    name = m.group(1).strip().rstrip(".:").strip()
    rest = re.split(r"(?<=[.!?])\s|;\s", m.group(2), maxsplit=1)[0].strip().rstrip(".;:")
    return cut(f"{name}: {rest}" if rest else name, MAX_AREA)


def lead(bullet: str) -> str:
    text = bullet[2:].strip()
    m = re.match(r"\*\*(.+?)\*\*", text)
    if m:
        return m.group(1).strip().rstrip(".:").strip()
    clause = re.split(r"(?<=[.;:!?])\s|\s[—–]\s", text, maxsplit=1)[0].rstrip(".;:")
    if len(clause) > MAX_CLAUSE:
        clause = clause[:MAX_CLAUSE].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    return clause


def count_line(counts: dict[str, int]) -> str:
    names = [k for k in KIND_ORDER if counts.get(k)] + [
        k for k in counts if k not in KIND_ORDER and counts[k]]
    return " · ".join(f"{k} {counts[k]}" for k in names)


# --- rendering -----------------------------------------------------------------------------

def index_entry(version: str, body: str) -> str:
    counts, highlights = summarise(body)
    out = [f"### [{version}]({SITE}/changelog/{version}/)", ""]
    line = count_line(counts)
    if line:
        out += [line, ""]
    out += [f"- {h}" for h in highlights]
    return "\n".join(out).rstrip() + "\n"


def render_index(docs: Path) -> str:
    releases = []
    for p in docs.glob("*.md"):
        version, date, body = read_doc(p)
        if p.stem != version:
            raise SystemExit(f"{p}: file name and heading disagree ({version})")
        releases.append((date, version, body))
    releases.sort(key=lambda r: (r[0], _vkey(r[1])), reverse=True)
    blocks, day = [], None
    for date, version, body in releases:
        if date != day:
            blocks.append(f"## {date}\n")
            day = date
        blocks.append(index_entry(version, body))
    return "\n".join(blocks)


def unreleased_span(text: str) -> tuple[int, int]:
    """Start of the [Unreleased] body and where it ends: the intro line or the first release."""
    start = text.index(UNRELEASED) + len(UNRELEASED)
    ends = [len(text)]
    m = re.search(r"^## (?!\[Unreleased\])", text[start:], re.M)
    if m:
        ends.append(start + m.start())
    if INTRO.strip() in text[start:]:
        ends.append(start + text[start:].index(INTRO.strip()))
    return start, min(ends)


def head_of(text: str) -> str:
    """Everything up to the index: the preamble and the whole [Unreleased] section."""
    return text[: unreleased_span(text)[1]].rstrip("\n") + "\n\n"


INTRO = ("Full notes for each release are in [`docs/changelog/`](docs/changelog/), also on the "
         "docs site. One entry per release below: counts, then highlights.\n\n")


def write_index(root: Path) -> None:
    changelog, docs, mkdocs = _paths(root)
    text = changelog.read_text()
    changelog.write_text(head_of(text) + INTRO + render_index(docs))
    update_nav(mkdocs, docs)


def update_nav(mkdocs: Path, docs: Path) -> None:
    if not mkdocs.exists():
        return
    versions = sorted((p.stem for p in docs.glob("*.md")), key=_vkey, reverse=True)
    block = "  - Changelog:\n" + "".join(f"      - {v}: changelog/{v}.md\n" for v in versions)
    lines = mkdocs.read_text().splitlines(keepends=True)
    for i, line in enumerate(lines):
        if line.rstrip() == "  - Changelog:":
            j = i + 1
            while j < len(lines) and lines[j].startswith("      "):
                j += 1
            lines[i:j] = [block]
            break
    else:
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        lines.append(block)
    mkdocs.write_text("".join(lines))


# --- commands ------------------------------------------------------------------------------

def migrate(root: Path) -> None:
    changelog, docs, _ = _paths(root)
    text = changelog.read_text()
    _, _, sections = split_changelog(text)
    docs.mkdir(parents=True, exist_ok=True)
    for version, date, body in sections:
        (docs / f"{version}.md").write_text(doc_text(version, date, body))
    changelog.write_text(head_of(text))
    write_index(root)


def release(root: Path, version: str, date: str) -> None:
    if not re.fullmatch(r"\d+\.\d+\.\d+", version) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        raise SystemExit("usage: release X.Y.Z YYYY-MM-DD")
    changelog, docs, _ = _paths(root)
    target = docs / f"{version}.md"
    if target.exists():
        raise SystemExit(f"{target} already exists; released notes are never rewritten")
    text = changelog.read_text()
    start, end = unreleased_span(text)
    body = text[start:end]
    if not body.strip():
        raise SystemExit("[Unreleased] is empty; nothing to release")
    docs.mkdir(parents=True, exist_ok=True)
    target.write_text(doc_text(version, date, body))
    changelog.write_text(text[:start] + "\n" + text[end:])
    write_index(root)


def main(argv: list[str]) -> int:
    if len(argv) == 4 and argv[1] == "release":
        release(ROOT, argv[2], argv[3])
    elif len(argv) == 2 and argv[1] == "rebuild":
        write_index(ROOT)
    elif len(argv) == 2 and argv[1] == "migrate":
        migrate(ROOT)
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
