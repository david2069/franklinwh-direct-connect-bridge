"""#736 phase 1: HEMS has its own section in the guide.

Nine pages under docs/guide/hems/, in the nav as one group. The HEMS setup, battery wear and
Load Forecast texts moved there (owner 2026-11-18); each old place keeps a summary and a link.
The cards' Guide links open the new pages."""
import pathlib
import re

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
GUIDE = ROOT / "docs/guide"
HEMS = GUIDE / "hems"
SRC = ROOT / "src/franklinwh_direct_connect_bridge"

PAGES = ("index", "getting-started", "solar-forecast", "load-forecast", "battery-wear",
         "loads", "scheduler", "home-assistant", "troubleshooting")


def _nav():
    class _Loader(yaml.SafeLoader):
        pass
    # mkdocs.yml has !!python/name tags (emoji); read them as plain strings
    _Loader.add_multi_constructor("tag:yaml.org,2002:python/", lambda l, s, n: None)
    return yaml.load((ROOT / "mkdocs.yml").read_text(), Loader=_Loader)["nav"]


def _find_group(node, title):
    if isinstance(node, list):
        for x in node:
            r = _find_group(x, title)
            if r is not None:
                return r
    elif isinstance(node, dict):
        for k, v in node.items():
            if k == title:
                return v
            r = _find_group(v, title)
            if r is not None:
                return r
    return None


def test_every_hems_page_exists_and_is_in_the_nav():
    group = _find_group(_nav(), "HEMS (energy planning)")
    assert group is not None, "no 'HEMS (energy planning)' group in the nav"
    for p in PAGES:
        assert (HEMS / f"{p}.md").exists(), p
        assert f"guide/hems/{p}.md" in group, p


def test_the_overview_says_what_hems_does_not_do_yet():
    text = (HEMS / "index.md").read_text()
    assert "never writes to the aGate" in text
    assert "#612" in text and "planner" in text.lower()
    assert "Planning is only as accurate as your answers." in text


def test_moved_texts_live_in_the_new_pages_once():
    # the wear figures table, the heavy-load control types and the Load Forecast paragraph
    assert "| Wear cost |" in (HEMS / "battery-wear.md").read_text()
    assert "| Wear cost |" not in (GUIDE / "health-report.md").read_text()
    assert "*deferrable*" in (HEMS / "loads.md").read_text()
    assert "*deferrable*" not in (GUIDE / "energy-and-costs.md").read_text()
    assert "add the entity to the recorder's `exclude`" in (HEMS / "load-forecast.md").read_text()
    assert "add the entity to the recorder's `exclude`" not in (GUIDE / "home-assistant.md").read_text()


def test_each_old_place_keeps_a_summary_and_a_link():
    for page, heading, target in (
            ("energy-and-costs.md", "## HEMS setup", "hems/loads.md"),
            ("health-report.md", "## Battery warranty and wear", "hems/battery-wear.md"),
            ("home-assistant.md", "**Load Forecast**", "hems/load-forecast.md"),
            ("energy-and-costs.md", "## Solar forecast", "hems/solar-forecast.md"),
            ("scheduler/conditions.md", "### Solar Forecast", "../hems/scheduler.md")):
        text = (GUIDE / page).read_text()
        assert heading in text, (page, heading)
        assert target in text, (page, target)


def test_the_cards_open_the_new_pages():
    html = (SRC / "templates/tabs/settings.html").read_text()
    links = re.findall(r"guideUrl\('([^']+)'\)", html)
    assert "hems/battery-wear" in links
    assert "hems/loads" in links
