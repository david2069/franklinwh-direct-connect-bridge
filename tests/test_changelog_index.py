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
    assert "- Billing: one bill" in text and "- Retailers: dates save" in text and "Ignored" not in text
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


def test_area_lines_carry_their_text():
    line = ("- **Billing:** two gateways on one meter share one bill; each aGate's built-in grid CT "
            "counts as its own part, with nothing to set.")
    assert ci.area_line(line) == "Billing: two gateways on one meter share one bill"
    long = "- **Area:** " + "word " * 40
    out = ci.area_line(long)
    assert out.startswith("Area: word") and out.endswith("…") and len(out) <= ci.MAX_AREA + 1


def test_index_has_its_own_heading_and_a_link_that_works_in_ha(tmp_path):
    """HA's update dialog showed the index under [Unreleased], and its relative link
    went nowhere there."""
    root = make(tmp_path)
    ci.release(root, "1.3.0", "2026-03-03")
    text = (root / "CHANGELOG.md").read_text()
    unreleased = text.split("## [Unreleased]")[1].split("\n## ")[0]
    assert unreleased.strip() == "", unreleased
    assert "## Releases\n" in text
    assert text.index("## Releases") < text.index("## 2026-03-03")
    assert "](docs/changelog/)" not in text
    assert f"]({ci.REPO_URL}/tree/main/docs/changelog)" in text.split("## 2026-03-03")[0]


def test_old_intro_is_replaced_on_rebuild(tmp_path):
    root = make(tmp_path)
    old = ("Full notes for each release are in [`docs/changelog/`](docs/changelog/), also on the "
           "docs site. One entry per release below: counts, then highlights.\n\n")
    p = root / "CHANGELOG.md"
    p.write_text(p.read_text().replace(ci.INTRO, old))
    ci.write_index(root)
    text = p.read_text()
    assert "](docs/changelog/)" not in text and text.count("## Releases") == 1


def test_index_links_go_to_the_notes_on_github(tmp_path):
    """Owner 2026-11-16: the docs site can lag a release (its deploy is separate), so the
    index links to the notes file in the repo, which a release always contains."""
    root = make(tmp_path)
    text = (root / "CHANGELOG.md").read_text()
    assert f"### [1.2.0]({ci.REPO_URL}/blob/main/docs/changelog/1.2.0.md)" in text


def test_release_rewrites_repo_links_so_the_notes_work_from_docs_changelog(tmp_path):
    """0.5.46's docs deploy failed: links written for CHANGELOG.md at the repo root
    (docs/guide/x.md, INSTALL.md) are broken from docs/changelog/, and the strict build
    stops. Moved notes get links that work from there, on GitHub and on the docs site."""
    root = make(tmp_path)
    text = (root / "CHANGELOG.md").read_text().replace(
        "- **Shiny thing** (#1). Does it.",
        "- **Shiny thing** (#1). See [the guide](docs/guide/x.md#how), [install](INSTALL.md), "
        "[web](https://example.com/a.md) and [here](#top).")
    (root / "CHANGELOG.md").write_text(text)
    ci.release(root, "1.3.0", "2026-03-03")
    doc = (root / "docs" / "changelog" / "1.3.0.md").read_text()
    assert "[the guide](../guide/x.md#how)" in doc
    assert f"[install]({ci.REPO_URL}/blob/main/INSTALL.md)" in doc
    assert "[web](https://example.com/a.md)" in doc and "[here](#top)" in doc
