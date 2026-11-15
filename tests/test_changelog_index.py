"""The changelog is a short index over full per-version notes (docs/TEST_POLICY.md)."""
import importlib.util
import re
import shutil
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("changelog_index", REPO / "tools" / "changelog_index.py")
ci = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ci)

FIXTURE = """# Changelog

Preamble line.

## [Unreleased]

### Added
- **Shiny thing** (#1). Does it.

## [1.2.0] — 2026-02-02

### Added
- **Alpha** one. More text.
- **Beta** two.
  - nested bullet is not counted

### Fixed
- A fix without a bold lead-in that goes on and on and on well past the eighty character limit here.

### Security
- **Locked** down.

## [1.1.0] — 2026-02-02

Everything merged since 1.0.0, by area:

- **Billing:** one bill.
- **Retailers:** dates save.

### Fixed
- **Ignored** because the area lines win.

## [1.0.0] — 2026-01-01

### Removed
- **Gone**.
"""


def make(tmp_path, text=FIXTURE):
    (tmp_path / "CHANGELOG.md").write_text(text)
    (tmp_path / "mkdocs.yml").write_text("nav:\n  - Home: index.md\n")
    ci.migrate(tmp_path)
    return tmp_path


def test_round_trip_is_verbatim(tmp_path):
    _, _, sections = ci.split_changelog(FIXTURE)
    root = make(tmp_path)
    assert len(sections) == 3
    for version, date, body in sections:
        doc = (root / "docs" / "changelog" / f"{version}.md").read_text()
        assert doc.startswith(f"# {version} — {date}\n\n")
        assert body.strip("\n") in doc


def test_counts_highlights_and_grouping(tmp_path):
    text = make(tmp_path) and (tmp_path / "CHANGELOG.md").read_text()
    assert text.count("## 2026-02-02") == 1  # two releases, one day heading
    assert "Added 2 · Fixed 1 · Security 1" in text  # nested bullet not counted
    assert "- Alpha" in text and "- Beta" in text
    cut = [l for l in text.splitlines() if l.startswith("- A fix without")]
    assert len(cut) == 1 and cut[0].endswith("…") and len(cut[0]) <= 2 + ci.MAX_CLAUSE + 1
    assert "- Billing" in text and "- Retailers" in text and "Ignored" not in text
    assert "Removed 1" in text
    assert text.index("## 2026-02-02") < text.index("## 2026-01-01")
    assert text.index("### [1.2.0]") < text.index("### [1.1.0]")
    assert "[Unreleased]" in text and "**Shiny thing** (#1). Does it." in text
    assert text.startswith("# Changelog\n\nPreamble line.\n")


def test_nav_lists_versions_newest_first(tmp_path):
    root = make(tmp_path)
    nav = (root / "mkdocs.yml").read_text()
    assert nav.index("1.2.0") < nav.index("1.1.0") < nav.index("1.0.0")


def test_release_moves_unreleased(tmp_path):
    root = make(tmp_path)
    ci.release(root, "1.3.0", "2026-03-03")
    doc = (root / "docs" / "changelog" / "1.3.0.md").read_text()
    assert doc == "# 1.3.0 — 2026-03-03\n\n### Added\n- **Shiny thing** (#1). Does it.\n"
    text = (root / "CHANGELOG.md").read_text()
    assert "Shiny thing** (#1)" not in text
    assert re.search(r"## \[Unreleased\]\n\n## 2026-03-03\n\n### \[1\.3\.0\]", text.replace(ci.INTRO, ""))
    before = (root / "docs" / "changelog" / "1.2.0.md").read_text()
    ci.write_index(root)  # rebuild is stable and leaves released notes alone
    assert (root / "docs" / "changelog" / "1.2.0.md").read_text() == before
    assert text == (root / "CHANGELOG.md").read_text()


def test_release_refuses_empty_unreleased_and_existing_version(tmp_path):
    root = make(tmp_path)
    ci.release(root, "1.3.0", "2026-03-03")
    for args in (("1.4.0", "2026-03-04"), ("1.2.0", "2026-03-04")):
        try:
            ci.release(root, *args)
        except SystemExit:
            continue
        raise AssertionError(f"release {args} should have been refused")


def test_repo_index_matches_docs():
    docs = REPO / "docs" / "changelog"
    text = (REPO / "CHANGELOG.md").read_text()
    assert "## [Unreleased]" in text
    files = sorted(p.stem for p in docs.glob("*.md"))
    assert files, "no per-version notes"
    for version in files:
        assert f"### [{version}](" in text, f"{version} missing from the CHANGELOG index"
        assert f"changelog/{version}.md" in (REPO / "mkdocs.yml").read_text()
    assert text.split("## [Unreleased]")[1].count("### [") == len(files)
    assert not re.search(r"^## \[\d", text, re.M), "released notes belong in docs/changelog/"
