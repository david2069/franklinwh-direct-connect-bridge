"""#306: Guide opens the page for the tab on screen, and section links open the topic.

Every link is checked against the guide's Markdown source: the page must exist and the
anchor must be one of its headings, slugged as MkDocs does. A renamed heading fails here
instead of landing the user at the top of a page."""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src/franklinwh_direct_connect_bridge"
GUIDE = ROOT / "docs/guide"


def _slug(heading: str) -> str:            # MkDocs toc default slugify
    s = re.sub(r"[^\w\s-]", "", heading.strip().lower())
    return re.sub(r"[\s]+", "-", s)


def _resolve(link: str) -> None:
    page, _, anchor = link.partition("#")
    page = page.strip("/")
    md = GUIDE / (page + ".md") if page else GUIDE / "index.md"
    if not md.exists():
        md = GUIDE / page / "index.md"
    assert md.exists(), f"{link}: no guide page {page}"
    if anchor:
        heads = {_slug(h) for h in re.findall(r"^#{1,6} (.+)$", md.read_text(), re.M)}
        assert anchor in heads, f"{link}: no heading #{anchor} in {md.name}"


def _links():
    js = (SRC / "static/js/app.js").read_text()
    block = re.search(r"const GUIDE_PAGES = \{(.*?)\};", js, re.S).group(1)
    pages = dict(re.findall(r"(\w+): '([^']*)'", block))
    sections = []
    for tpl in (SRC / "templates").rglob("*.html"):
        sections += re.findall(r"guideUrl\('([^']+)'\)", tpl.read_text())
    return pages, sections


def test_every_tab_has_a_guide_page():
    js = (SRC / "static/js/app.js").read_text()
    tabs = set(re.findall(r"\{ key: '(\w+)', title:", js))
    pages, _ = _links()
    assert tabs, "tab list not found"
    assert not tabs - set(pages), f"tabs with no guide page: {sorted(tabs - set(pages))}"


def test_every_link_lands_on_a_real_heading():
    pages, sections = _links()
    assert len(sections) >= 4
    for link in list(pages.values()) + sections:
        _resolve(link)


def test_the_sidebar_and_phone_menu_follow_the_tab():
    for p in ("templates/partials/sidebar.html", "templates/partials/bottom-nav.html"):
        assert ':href="$store.app.guideUrl()"' in (SRC / p).read_text(), p
