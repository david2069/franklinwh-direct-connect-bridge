"""A tab drops one gateway's data when you switch to another (#352). (Site view, whose
writes #350 refused, is gone: #383.)"""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1] / "src/franklinwh_direct_connect_bridge"
JS = ROOT / "static/js"
TPL = ROOT / "templates"


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
