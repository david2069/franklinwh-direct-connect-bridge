"""Every dialog sits above the phone's bottom nav (#734). Eight dialogs were z-50 under the
nav's z-[70]: on an iPhone the nav covered the Edit schedule footer, so Save and Cancel
could not be reached. The schedule form fits the visible viewport (dvh, with a vh
fallback and the iOS safe area) and its body scrolls."""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1] / "src/franklinwh_direct_connect_bridge"
TPL = ROOT / "templates"
NAV = (TPL / "partials/bottom-nav.html").read_text()
CSS = (ROOT / "static/css/design-system.css").read_text()
SCHED = (TPL / "tabs/scheduler.html").read_text()


def _z(cls: str) -> int:
    m = re.search(r"\bz-(?:\[(\d+)\]|(\d+))", cls)
    return int(m.group(1) or m.group(2))


def test_every_dialog_overlay_is_above_the_bottom_nav():
    nav_z = _z(re.search(r'<nav[^>]*class="([^"]*)"', NAV).group(1))
    low = []
    for f in TPL.rglob("*.html"):
        for cls in re.findall(r'class="(fixed inset-0 z-[^"]*)"', f.read_text()):
            if f.name == "bottom-nav.html":
                continue                       # the nav's own More sheet
            if _z(cls) <= nav_z:
                low.append(f"{f.relative_to(TPL)}: {cls[:40]}")
    assert not low, low


def test_schedule_form_fits_the_visible_viewport_and_scrolls():
    i = SCHED.index("dialogSize('fwh-dlg-schedule-edit')")
    overlay = SCHED[SCHED.rindex("<div", 0, SCHED.rindex("<div", 0, i)):i]
    assert "safe-area-inset-bottom" in overlay
    body = SCHED[SCHED.index('class="flex-1 overflow-y-auto px-5 py-4', i):][:200]
    assert "-webkit-overflow-scrolling:touch" in body.replace(" ", "")
    # without dvh (iOS < 15.4) the inline 90dvh is dropped: the stylesheet still caps it
    assert re.search(r'\[x-data\^="dialogSize"\]\s*\{[^}]*max-height:\s*90vh', CSS)


def test_sized_dialog_never_outgrows_its_backdrop():
    js = (ROOT / "static/js/app.js").read_text()
    assert "maxHeight: 'min(90dvh, calc(100% - 1rem))'" in js
