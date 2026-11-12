"""The Audit trail is a sub-tab of Logs, and readable (owner, 2026-11-12: "Audit trail
should be a sub tab under logs. It's hard to read due to the shading effect. Can you
remove it?")."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src/franklinwh_direct_connect_bridge"
LOGS = (ROOT / "templates/tabs/logs.html").read_text()
CONTROL = (ROOT / "templates/tabs/control.html").read_text()
ALERTS = (ROOT / "static/js/alerts.js").read_text()


def _audit_block(html):
    start = html.index('data-testid="audit-trail"')
    return html[start:html.index("</template>", start)]


def test_the_audit_trail_is_a_logs_sub_tab():
    assert 'data-testid="audit-trail"' in LOGS
    assert "$store.app.logsView === 'audit'" in LOGS and "$store.app.logsView === 'log'" in LOGS
    assert "loadControlLog()" in LOGS


def test_the_control_tab_no_longer_carries_it():
    assert "Audit trail" not in CONTROL and "controlLog" not in CONTROL


def test_rows_are_not_shaded():
    block = _audit_block(LOGS)
    assert "surface-2" not in block and "text-slate-500" not in block and "truncate" not in block


def test_alerts_open_logs_on_the_audit_trail():
    assert "Control tab" not in ALERTS
    assert "view: 'audit'" in ALERTS and "logsView" in ALERTS
