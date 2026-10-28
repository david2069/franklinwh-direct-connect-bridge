"""The UI writes only to the gateway on screen: Site view refuses per-gateway writes
(#350), and a tab drops one gateway's data when you switch to another (#352)."""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1] / "src/franklinwh_direct_connect_bridge"
JS = ROOT / "static/js"
TPL = ROOT / "templates"

# Writes that may stay on gwQuery(): the topbar Release walks each held gateway itself
# (#349); the scheduler's per-row Run/evaluate are #359; the dry-run preview is a read.
_ALLOWED = {
    ("app.js", "api/battery/command' + t.q"),
    ("scheduler_tab.js", "api/schedules/"),
    ("mqtt_tab.js", "unpublish?dry_run=true"),
}


def _write_calls():
    """(file, fetch line) for every fetch whose options say POST/PUT/PATCH/DELETE."""
    out = []
    for f in sorted(JS.glob("*.js")):
        if f.name.endswith(".min.js"):
            continue
        lines = f.read_text().split("\n")
        for i, line in enumerate(lines):
            if "fetch(" not in line:
                continue
            window = " ".join(lines[i:i + 3])
            if re.search(r"method:\s*'(POST|PUT|PATCH|DELETE)'", window):
                out.append((f.name, line))
    return out


def test_every_per_gateway_write_is_refused_in_site_view():
    leaks = [(f, l.strip()) for f, l in _write_calls()
             if ".gwQuery(" in l and not any(f == af and s in l for af, s in _ALLOWED)]
    assert leaks == []
    users = {f for f, l in _write_calls() if ".writeQuery(" in l}
    assert {"app.js", "circuits_tab.js", "generator_tab.js", "grid_tab.js", "device_tab.js",
            "terminal.js", "mqtt_tab.js", "battery_tab.js", "energy_costs_tab.js",
            "settings_tab.js", "battery_control.js"} <= users


def test_write_query_throws_in_site_view_and_site_summary_turns_writes_off():
    app = (JS / "app.js").read_text()
    body = app[app.index("    writeQuery(sep = '?') {"):]
    body = body[:body.index("\n    },")]
    assert "if (this.siteMode) throw new Error(this.siteWriteNote);" in body
    assert "siteWriteNote: 'Choose a gateway to change this.'" in app
    site = app[app.index("async _pollSite()"):]
    site = site[:site.index("this._noteConnOk(this.summary)")]
    assert "writes_enabled: false" in site


def test_site_view_disables_each_write_control_and_says_why():
    note = 'x-text="$store.app.siteWriteNote"'
    expect = {
        "partials/topbar.html": ':disabled="m.active || $store.app.siteMode"',
        "tabs/grid.html": '@click="openModal()" :disabled="$store.app.siteMode"',
        "tabs/device.html": ':disabled="conBusy || $store.app.siteMode"',
        "tabs/mqtt.html": '@click="unpublish()" class="btn btn-secondary btn-sm" :disabled="$store.app.siteMode"',
        "tabs/battery.html": ':disabled="$store.app.siteMode" x-show="!rec.active">Record',
        "tabs/energy_costs.html": '@click="openModbusImport()" :disabled="$store.app.siteMode"',
        "tabs/settings.html": "systemSaving || $store.app.siteMode || !systemCurrent",
        "tabs/circuits.html": ":title=\"$store.app.siteMode ? $store.app.siteWriteNote",
        "tabs/generator.html": ":title=\"$store.app.siteMode ? $store.app.siteWriteNote",
        "tabs/dashboard.html": note,
    }
    for path, marker in expect.items():
        html = (TPL / path).read_text()
        assert marker in html, path
        assert "siteWriteNote" in html, path
    # The read-only notices don't claim writes are off in Site view: it says why instead.
    control = (TPL / "tabs/control.html").read_text()
    assert control.count("!$store.app.summary.writes_enabled && !$store.app.siteMode") == 3


def test_per_gateway_tabs_drop_their_data_on_a_gateway_switch():
    assert "function clearOnGatewaySwitch(cmp, key, clear)" in (JS / "app.js").read_text()
    for f, key in [("circuits_tab.js", "circuits"), ("generator_tab.js", "generator"),
                   ("solar_tab.js", "solar"), ("health_tab.js", "health"),
                   ("device_tab.js", "device")]:
        assert f"clearOnGatewaySwitch(this, '{key}'" in (JS / f).read_text(), f
    gen = (JS / "generator_tab.js").read_text()
    assert "this.closeEdit(); });" in gen            # an open editor never outlives a switch


def test_a_late_reply_for_the_previous_gateway_is_dropped():
    for f in ["circuits_tab.js", "generator_tab.js", "solar_tab.js", "health_tab.js",
              "settings_tab.js"]:
        src = (JS / f).read_text()
        assert "const gwq = this.$store.app.gwQuery();" in src, f
        assert "gwq === this.$store.app.gwQuery()" in src or "gwq !== this.$store.app.gwQuery()" in src, f
    assert "if (gwq !== this.app.gwQuery('?')) return;" in (JS / "device_tab.js").read_text()


def test_system_setup_is_reread_on_a_switch_and_save_waits_for_it():
    src = (JS / "settings_tab.js").read_text()
    assert "this.$watch('$store.app.selectedGateway'" in src
    assert "get systemCurrent() { return this.systemFor === this.$store.app.gwQuery(); }" in src
    save = src[src.index("async saveSystemSetup()"):]
    assert "if (!this.systemCurrent) return;" in save[:save.index("fetch(")]


def test_system_setup_watchers_register_once_although_init_runs_twice():
    # settings.html has x-data="settingsTab()" x-init="init()", so init() runs twice.
    src = (JS / "settings_tab.js").read_text()
    assert src.count("if (!this._systemWatched) this.$watch(") == 2
    assert "this._systemWatched = true;" in src
