"""Smart Dispatch on a phone (owner 2026-11-28): the objective question's dropdown sized itself
to its longest option ("Self-consumption: use my own solar and battery first") and ran past the
card's edge. The question dropdowns stay inside the card."""
import pathlib
import re

PKG = pathlib.Path(__file__).resolve().parents[1] / "src" / "franklinwh_direct_connect_bridge"


def test_question_dropdowns_fit_a_phone():
    html = (PKG / "templates/tabs/smart_dispatch.html").read_text()
    line = next(ln for ln in html.splitlines() if "'sd-q-' + q.key" in ln and "<select" in ln)
    classes = re.search(r'class="([^"]*)"', line).group(1).split()
    assert "max-w-full" in classes and "w-full" in classes and "w-auto" not in classes
