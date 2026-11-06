"""Alpine 3 calls a component's init() itself, so x-init="init()" runs it twice (#376)."""
import pathlib
import re

TPL = pathlib.Path(__file__).resolve().parents[1] / "src/franklinwh_direct_connect_bridge/templates"


def test_no_template_calls_init_again_from_x_init():
    hits = []
    for f in sorted(TPL.rglob("*.html")):
        for tag in re.findall(r"<[^>]*\bx-data=\"\w+\(\)\"[^>]*>", f.read_text()):
            if 'x-init="init()"' in tag:
                hits.append(f"{f.relative_to(TPL)}: {tag[:60]}")
    assert hits == []
