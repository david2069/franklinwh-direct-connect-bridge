"""Every device-reaching UI call must be scoped to the SELECTED gateway.

Filed after a real defect: circuits/generator/solar/battery all fetched without
``?gateway=``, so on a multi-gateway site they showed the DEFAULT gateway while
the topbar said otherwise. Latent on a single-gateway site — nothing caught it,
because ``gwQuery()`` returns '' when there is only one gateway, so the calls
looked correct in every test and every live check.

This scans the tab controllers directly rather than trusting review.
"""
import pathlib
import re

import pytest

JS_DIR = pathlib.Path(__file__).resolve().parents[1] / \
    "src/franklinwh_direct_connect_bridge/static/js"

#: Endpoints that do NOT reach a gateway, so a gateway parameter would be
#: meaningless. Each must stay justified — this list is the exemption, not a
#: dumping ground.
NOT_DEVICE_BOUND = {
    "api/battery/sessions",        # SQLite: recorded sessions, already gateway-tagged
    "api/battery/record/stop",     # process-level: stops the running recorder
    "api/battery/record/status",   # process-level: progress of the running recorder
    "api/gateways",                # the gateway list itself
    "api/sites",                   # site roster — global config, not per-gateway
    "api/meters",                  # meter roster — global config, not per-gateway
    "api/utilities",               # utility roster — global config, not per-gateway
    "api/tariffs",                 # tariff roster — global config, not per-gateway
    "api/constants",               # automation constants — global config, not per-gateway
    "api/mqtt/groups",             # MQTT publish-group preference — global, not per-gateway
    "api/admin",                   # DB storage/backup/restore/vacuum/export — bridge-wide DB (rows gateway-tagged inside), not a device read
    "api/summary",                 # already resolves the gateway server-side
    "api/logs",                    # bridge process log, not a device read
    "api/mqtt/discover",           # broker discovery, bridge-wide
    "api/billing",                 # billing overview/history — resolves the meter server-side, not a device read
    "api/notify",                  # notify triggers / log / test / devices — bridge-wide
    "api/notify/test",             # sends a test notification via HA, no gateway
    "api/settings",                # bridge configuration, not per-gateway
    "api/cloud/validate",          # checks the bridge's cloud credentials, not a gateway
    "api/cloud/pop",               # CloudFront PoP edge metrics — account-level, not per-gateway
    "api/tariff/spot",             # AEMO NEM wholesale spot — account/region-level, not per-gateway
    "api/support-info",            # redacted diagnostic bundle — spans ALL gateways, not one
    "api/disclaimer",              # legal disclaimer text/ack — app-level, not per-gateway
    "api/site/timezone",           # settings_tab scopes it PER-ROW (explicit ?gateway=<id> for each
                                   # gateway in the table), not via the selected-gateway gwQuery; app.js uses gwQuery.
    "api/raw/catalog",             # static cmdType catalog, identical for every gateway
    "api/schedules",               # schedule definitions are bridge-wide config; the
                                   # one call that reaches a device (/run) DOES scope.
    "api/ha",                      # Home Assistant instances are bridge-wide config,
                                   # not per-gateway: one bridge feeds many HAs and
                                   # reads their entities regardless of which gateway
                                   # is selected.
}

#: A call may scope itself inline (``gwQuery(...)``) or via a local built from it —
#: mqtt_tab.js does ``const gwq = ...gwQuery('?')`` then appends ``gwq``. Both are
#: correct; only an UNSCOPED call is a bug. Any name here must be proven to come
#: from gwQuery() by :func:`test_scoping_locals_really_derive_from_gwquery`.
SCOPE_TOKENS = ("gwQuery(", "gwq")

_FETCH = re.compile(r"fetch\(\s*([`'\"])(api/[^`'\"$]*)")


def _strip_comments(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group().count("\n"), src, flags=re.S)
    return re.sub(r"^\s*//.*$", "", src, flags=re.M)


def _tab_files():
    return sorted(JS_DIR.glob("*_tab.js"))


def test_tab_controllers_exist():
    assert _tab_files(), "no *_tab.js found — has the layout changed?"


@pytest.mark.parametrize("path", _tab_files(), ids=lambda p: p.name)
def test_every_device_call_is_gateway_scoped(path):
    src = _strip_comments(path.read_text())
    unscoped = []
    for m in _FETCH.finditer(src):
        endpoint = m.group(2).split("?")[0].rstrip("/")
        if any(endpoint.startswith(x) for x in NOT_DEVICE_BOUND):
            continue
        # The gwQuery() call must appear in the same statement as the fetch.
        tail = src[m.end():m.end() + 240]
        if not any(t in tail for t in SCOPE_TOKENS):
            unscoped.append(endpoint)
    assert not unscoped, (
        f"{path.name}: device call(s) not scoped to the selected gateway: "
        f"{sorted(set(unscoped))}. Append this.$store.app.gwQuery() — or add the "
        f"endpoint to NOT_DEVICE_BOUND with a reason if it never reaches a gateway."
    )


@pytest.mark.parametrize("path", _tab_files(), ids=lambda p: p.name)
def test_scoping_locals_really_derive_from_gwquery(path):
    """``gwq`` counts as scoping only if it is actually built from gwQuery()."""
    src = _strip_comments(path.read_text())
    if re.search(r"\bgwq\b", src) is None:
        pytest.skip("no gwq local in this tab")
    assert re.search(r"gwq\s*=\s*[^;]*gwQuery\(", src), (
        f"{path.name}: uses a 'gwq' identifier that is not assigned from gwQuery()"
    )


def test_query_string_calls_use_the_ampersand_separator():
    """gwQuery() defaults to '?'; a call that already has one needs gwQuery('&')."""
    for path in _tab_files():
        src = _strip_comments(path.read_text())
        for m in _FETCH.finditer(src):
            if "?" not in m.group(2) and "?' +" not in src[m.start():m.end() + 40]:
                continue
            tail = src[m.end():m.end() + 240]
            if "gwQuery(" in tail:
                assert "gwQuery('&')" in tail, (
                    f"{path.name}: {m.group(2)} already carries a query string, so it "
                    f"needs gwQuery('&') — gwQuery() would emit a second '?'."
                )


def test_helper_is_a_noop_on_single_gateway():
    """The reason the bug was invisible: '' unless there are 2+ gateways."""
    app_js = (JS_DIR / "app.js").read_text()
    assert "gateways.length > 1 && this.selectedGateway" in app_js


def test_console_prefills_from_the_selected_command():
    """Selecting a reading below should point the console at it, with the payload
    that command actually reads with — 1725 must arrive as opt:1, not opt:0."""
    src = (JS_DIR / "device_tab.js").read_text()
    assert "conFromSelection" in src
    assert "read_payload" in src, "must use the catalog's read payload, not assume opt:0"
    # select() has to call it, or the link silently does nothing
    sel = src[src.index("    select(name) {"):]
    assert "conFromSelection" in sel[:400]


def test_readings_show_the_frame_that_was_sent():
    """The user should not have to trust a reconstruction of the request.

    The bridge returns the real frame in X-FWH-Request (recorded by the transport
    at send time) and the Device tab renders it beside each reading.
    """
    js = (JS_DIR / "device_tab.js").read_text()
    assert "X-FWH-Request" in js and "sentFrames" in js
    html = (JS_DIR.parents[1] / "templates/tabs/device.html").read_text()
    assert "sentFrameText(selected)" in html


def test_console_read_write_label_is_per_command():
    """UI bug: the banner called a successful 1725 READ a 'write'.

    `opt` is an operation SELECTOR, not a global read/write flag — 1725 reads
    with opt:1 and 1727 acts on opt:3 — so the label must compare against the
    command's own read opt, exactly as the server-side gate does.
    """
    js = (JS_DIR / "device_tab.js").read_text()
    block = js[js.index("get conIsWrite()"):js.index("get conKind()")]
    assert "read_payload" in block, "must use the command's read opt"
    assert "!== 0" not in block, "the opt !== 0 rule is what caused the bug"


def test_console_result_is_invalidated_when_the_payload_changes():
    """The 'Request sent' panel must never show a frame the editor no longer holds.

    Observed: the dataArea box read {} while Request sent showed {"opt":1} — a
    stale result from an earlier send, i.e. false provenance from the very panel
    built to provide provenance.
    """
    js = (JS_DIR / "device_tab.js").read_text()
    assert "conInvalidate()" in js
    html = (JS_DIR.parents[1] / "templates/tabs/device.html").read_text()
    assert '@input="conInvalidate()"' in html, "editing the payload must clear the result"
    assert "conPreset" in js


def test_der_comms_labels_are_plain():
    """Labels read as product names, not field names or acronyms."""
    html = (JS_DIR.parents[1] / "templates/tabs/dashboard.html").read_text()
    assert "SunSpec Modbus" in html
    assert "IEEE 2030.5/CSIP" in html
    assert "SEP2:" not in html


def test_health_is_the_firmware_detail_view():
    """Health is where firmware detail lives — it spells the tags out in words,
    where the Device tab shows the raw four-letter codes. The Device tab keeps
    its own generic reading and is deliberately left alone."""
    root = JS_DIR.parents[1]
    health = (root / "templates/tabs/health.html").read_text()
    assert 'x-data="healthTab"' in health
    assert "aPower ${dev.id}" in health, "per-battery firmware must be shown"
    js = (JS_DIR / "health_tab.js").read_text()
    assert "api/firmware/all" in js
    assert "gwQuery()" in js, "must honour the selected gateway"
    assert "SL_VER: 'SL_VER (undecoded)'" in js, "unknown tags must not be invented"


def test_firmware_tags_have_readable_labels():
    """FPGA_VER / DCDC_VER / TH_VER are unreadable raw. The Health card already
    spelled some out, so the detail view must not be the worse of the two."""
    src = (JS_DIR.parents[1] / "fieldschema.py").read_text()
    for tag in ("FPGA_VER", "DCDC_VER", "TH_VER", "BL_VER", "INV_VER", "BMS_VER"):
        assert f'"{tag}"' in src, f"{tag} has no label"
    assert "Thermal board" in src and "Bootloader" in src
    assert "SL_VER (undecoded)" in src, "unknown tags must say so, not be invented"


@pytest.mark.parametrize(
    "path", sorted((JS_DIR.parents[1] / "templates/tabs").glob("*.html")),
    ids=lambda p: p.name)
def test_tab_templates_have_balanced_divs(path):
    """A dropped </div> renders a blank tab with no error anywhere — exactly what
    happened to Health after an edit sliced off the file's closing tag."""
    src = path.read_text()
    opens = len(re.findall(r"<div\b", src))
    closes = src.count("</div>")
    assert opens == closes, f"{path.name}: {opens} <div> vs {closes} </div>"


def test_soc_is_rounded_not_shown_at_six_decimals():
    """The gateway reports SoC like 99.789474; the header showed it raw."""
    js = (JS_DIR / "app.js").read_text()
    block = js[js.index("get socPct()"):js.index("get ringOffset()")]
    assert "Math.round" in block, "socPct must round at the source (topbar + ring)"
    assert "socPct:" in js, "a whole-number %-suffixed formatter for the rows"


def test_topbar_mode_chip_is_a_switcher():
    """The mode chip was read-only display; the user wants to switch from the nav bar."""
    root = JS_DIR.parents[1]
    tb = (root / "templates/partials/topbar.html").read_text()
    assert "modeMenuOpen" in tb and "setMode(m.alias)" in tb
    js = (JS_DIR / "app.js").read_text()
    assert "get modeChoices()" in js
    # each choice must confirm — setMode already opens a confirmDialog
    block = js[js.index("async setMode(alias)"):]
    assert "confirmDialog" in block[:400]


def test_topbar_wraps_instead_of_overflowing():
    """On a phone the SoC/mode chips were pushed off-screen right; the header
    must wrap to a second line instead."""
    tb = (JS_DIR.parents[1] / "templates/partials/topbar.html").read_text()
    header = tb[tb.index("<header"):tb.index(">", tb.index("<header"))]
    assert "flex-wrap" in header, "the topbar header must wrap"


def test_tab_header_action_rows_wrap_on_mobile():
    """Header button groups (Refresh/Presets/Export/Add…) were running off the
    right edge on phones. The button group in each of these tabs must wrap."""
    tabs_dir = JS_DIR.parents[1] / "templates/tabs"
    for name in ("scheduler", "circuits", "generator", "solar", "mqtt"):
        html = (tabs_dir / f"{name}.html").read_text()
        assert "flex flex-wrap items-center gap-2" in html, (
            f"{name}.html header button group must use flex-wrap so it does not "
            f"overflow off-screen on mobile"
        )


def test_subtab_bars_scroll_horizontally():
    """Sub-tab bars (Schedules/Timeline/History, circuit/battery/HA tabs) must
    scroll rather than clip when they exceed the phone width."""
    tabs_dir = JS_DIR.parents[1] / "templates/tabs"
    for name in ("scheduler", "circuits", "battery", "ha"):
        html = (tabs_dir / f"{name}.html").read_text()
        assert "border-b overflow-x-auto" in html, (
            f"{name}.html sub-tab bar must be horizontally scrollable on mobile"
        )


def test_no_bare_box_drawing_dividers_in_js():
    """A section-divider comment that lost its `//` prefix is a JS syntax error
    that silently kills the whole component (schedulerTab did exactly this — no
    scheduler button worked). Guard every static JS file."""
    import glob, re
    js_dir = JS_DIR
    offenders = []
    for path in glob.glob(str(js_dir / "*.js")):
        for n, line in enumerate(open(path, encoding="utf-8"), 1):
            # a line that begins (after whitespace) with a box-drawing char is not
            # a comment and not valid JS
            if re.match(r"^\s*[─-╿]", line):
                offenders.append(f"{path.split('/')[-1]}:{n}")
    assert not offenders, f"bare box-drawing divider (missing // ) in: {offenders}"


def test_sidebar_auto_collapses_on_mobile():
    """The nav rail starts collapsed on narrow (phone) screens and honours a saved
    preference on desktop; a mobile session must not overwrite the desktop choice."""
    root = JS_DIR.parents[1]
    js = (JS_DIR / "app.js").read_text()
    assert "initSidebar(" in js and "toggleSidebar(" in js and "setSidebar(" in js
    assert "max-width: 699px" in js, "phones (< 700) collapse to the bottom bar; iPads get the sidebar"
    assert "fwh-sidebar-collapsed" in js
    assert "min-width: 700px" in js, "persist the collapse preference on tablet/desktop only"
    # all toggle sites route through the methods (no bare state flips)
    for f in ("partials/topbar.html", "partials/sidebar.html"):
        html = (root / "templates" / f).read_text()
        assert "sidebarCollapsed = !" not in html and "sidebarCollapsed = true" not in html \
            and "sidebarCollapsed = false" not in html, f"{f} still flips the state directly"
