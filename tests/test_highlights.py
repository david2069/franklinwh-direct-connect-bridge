"""Owner 2026-11-19: a Highlights section for the advanced features, in the README (above
"What it does") and on the docs home (above "Start here"), each linking its guide page."""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
FEATURES = ("Setup wizard", "Scheduler", "Analytics", "Health", "Network monitoring",
            "Notifications", "HEMS")


def _section(text, before):
    m = re.search(r"\n## Highlights\n(.*?)\n## " + re.escape(before), text, re.S)
    assert m, f"Highlights before {before}"
    return m.group(1)


def test_readme_and_docs_home_list_the_same_highlights_with_guide_links():
    readme = _section((ROOT / "README.md").read_text(), "What it does")
    home = _section((ROOT / "docs" / "index.md").read_text(), "Start here")
    for name in FEATURES:
        for where, sec, prefix in (("README", readme, "docs/guide/"), ("home", home, "guide/")):
            line = next((l for l in sec.splitlines() if l.startswith(f"- **[{name}]")), None)
            assert line, (where, name)
            target = re.search(r"\]\(([^)#]+)", line)[1]
            assert target.startswith(prefix), (where, name, target)
            base = ROOT if where == "README" else ROOT / "docs"
            assert (base / target).is_file(), (where, name, target)
