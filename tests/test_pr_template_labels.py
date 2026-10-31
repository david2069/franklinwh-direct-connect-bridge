"""The PR template names the labels CLAUDE.md says to use, and none of the retired ones.

The repository still has the older sev:S1-critical … S4-cosmetic labels on past issues,
so their existence on GitHub is not a reason to use them on new work.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / ".github" / "pull_request_template.md"
RETIRED = ("S1-critical", "S2-major", "S3-minor", "S4-cosmetic")


def test_template_uses_no_retired_labels():
    text = TEMPLATE.read_text(encoding="utf-8")
    assert [r for r in RETIRED if r in text] == []


def test_template_severities_are_the_policy_ones():
    named = set(re.findall(r"sev:S\d-[a-z]+", TEMPLATE.read_text(encoding="utf-8")))
    assert named == {"sev:S1-blocker", "sev:S2-high", "sev:S3-medium", "sev:S4-low"}


def test_template_says_refs_not_fixes():
    text = TEMPLATE.read_text(encoding="utf-8")
    assert "Refs #" in text and not re.search(r"^(Fixes|Closes) #", text, re.M)
