"""Alert UI wiring (#271, shared spec v1 §5). Render/wiring assertions — no JS runtime
here — so they guard the behaviours the spec fixes against markup drifting away."""

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import app as app_module

PKG = Path(app_module.__file__).parent
JS = (PKG / "static/js/alerts.js").read_text()
PARTIAL = (PKG / "templates/partials/alerts.html").read_text()


@pytest.fixture(scope="module")
def html():
    return TestClient(app_module.create_app()).get("/").text


def test_page_loads_the_alert_store_and_its_markup(html):
    assert "static/js/alerts.js" in html
    assert 'role="alertdialog"' in html                     # the modal
    assert "$store.alerts.activeAcked" in html              # the red bar
    assert "$store.alerts.summary.open" in html             # the badge


def test_every_page_load_fetches_the_open_set():
    init = JS[JS.index("init()"):JS.index("async poll(")]
    assert "this.poll()" in init
    assert "api/alerts?open=1" in JS and "api/status" in JS
    # Refetch only when open, latest_id or changed_ts changes (spec §4) — no SSE or WS.
    assert "`${s.open}|${s.latest_id}|${s.changed_ts}`" in JS
    assert "new EventSource" not in JS and "new WebSocket" not in JS


def test_the_modal_cannot_be_dismissed_without_acknowledging():
    modal = PARTIAL[:PARTIAL.index("Open alerts, from the top-bar badge")]
    assert "escape" not in modal.lower().replace("no escape handler", "")
    assert "@click=\"$store.alerts.listOpen" not in modal
    backdrop = re.search(r'<div class="absolute inset-0[^"]*"[^>]*>', modal).group(0)
    assert "@click" not in backdrop


def test_each_alert_has_its_own_checkbox_and_ok_waits_for_all():
    assert 'x-model="$store.alerts.understood[a.id]"' in PARTIAL
    assert ':disabled="!$store.alerts.allUnderstood' in PARTIAL
    assert "this.pending.every(a => this.understood[a.id])" in JS


def test_modal_queue_is_critical_unacknowledged_and_bar_is_active_acknowledged():
    assert "a.severity === 'critical' && !a.acked_ts" in JS
    assert "a.kind === 'condition' && !a.resolved_ts && a.acked_ts" in JS


def test_times_are_site_time_and_a_resolved_condition_shows_its_span():
    assert "_fmtSiteTime" in JS
    assert ", resolved`" in JS


def test_the_ui_acknowledges_as_source_ui():
    assert "JSON.stringify({ source: 'ui' })" in JS


def _order(block: str, *needles: str) -> list[int]:
    return [block.index(n) for n in needles]


def test_lists_show_time_first_then_message_then_delivery():
    row = PARTIAL[PARTIAL.index('x-for="a in $store.alerts.list"'):]
    pos = _order(row, "$store.alerts.when(a)", "a.message", "$store.alerts.delivery(a)")
    assert pos == sorted(pos)
    settings = (PKG / "templates/tabs/settings.html").read_text()
    log = settings[settings.index("Recent notifications"):]
    log = log[:log.index("</template>")]
    pos = _order(log, "fmtNotifyTime(e.ts)", "e.message", "e.device")
    assert pos == sorted(pos)


def test_every_catalogue_code_has_help_text():
    from franklinwh_direct_connect_bridge import alerts
    for code in alerts.CATALOGUE:
        assert f"{code}: {{" in JS, code


# ── ha_notify off (owner decision, franklinwh-modbus-bridge#324) ─────────────
def test_the_modal_does_not_depend_on_ha_notify():
    for src in (JS, PARTIAL):
        assert "ha_notify" not in src and "notif.master" not in src


def test_the_modal_set_is_served_with_ha_notify_off(monkeypatch):
    from franklinwh_direct_connect_bridge import alerts, config, db
    s = config.get_settings()
    monkeypatch.setattr(s, "ha_notify", False)
    a = alerts.raise_event(db.get_store(s), "gw1", "COMMAND_REFUSED", "x")
    rows = TestClient(app_module.create_app()).get("/api/alerts?open=1").json()["alerts"]
    assert [(r["id"], r["severity"], r["acked_ts"]) for r in rows] == [(a, "critical", None)]


def test_settings_warns_while_the_ha_channel_is_off():
    settings = (PKG / "templates/tabs/settings.html").read_text()
    i = settings.index('data-testid="ha-channel-off"')
    tag = settings[settings.rindex("<div", 0, i):settings.index(">", i)]
    assert 'x-show="notif.loaded && !notif.master"' in tag      # only while off
    assert "Critical alerts reach only the bridge UI" in settings[i:i + 400]
    # Beside the switch that IS ha_notify.
    assert settings.index("toggleMaster()") < i < settings.index("Auto-notify triggers")
    js = (PKG / "static/js/settings_tab.js").read_text()
    assert "this.form.ha_notify = next" in js and "this.notif.master = next" in js
