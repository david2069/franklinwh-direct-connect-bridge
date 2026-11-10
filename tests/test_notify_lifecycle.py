"""Bridge started / restarted / stopped notifications, and off-grid says why."""
import pathlib

from franklinwh_direct_connect_bridge import notify_engine
from franklinwh_direct_connect_bridge.db import MetricsStore

APP = pathlib.Path(notify_engine.__file__).with_name("app.py").read_text()


def _snap(off_grid=False, kind=None):
    return {"ok": True, "power": {"off_grid": off_grid, "off_grid_kind": kind, "soc": 50}}


# ── off-grid: user requested vs grid outage ──────────────────────────────────
def test_off_grid_says_user_requested_or_grid_outage():
    cfg = notify_engine.config(None)
    assert notify_engine.evaluate(_snap(True, "simulated"), _snap(), cfg) == [
        ("off_grid", {"reason": "user requested"})]
    assert notify_engine.evaluate(_snap(True, "outage"), _snap(), cfg) == [
        ("off_grid", {"reason": "grid outage"})]
    assert notify_engine.evaluate(_snap(True, None), _snap(), cfg) == [
        ("off_grid", {"reason": "reason unknown"})]
    _, msg = notify_engine.actionable.templates().render(
        "off_grid", gateway="Home", reason="user requested")
    assert msg == "Gateway went OFF-GRID [Home] (user requested) — running on battery."


# ── bridge lifecycle ─────────────────────────────────────────────────────────
def test_first_start_is_started_and_clean_stop_then_start_is_restarted(tmp_path):
    st = MetricsStore(str(tmp_path / "m.db"))
    assert notify_engine.bridge_up(st, "0.5.36", now=1000.0) == (
        "bridge_started", {"version": "0.5.36"})
    notify_engine.bridge_down(st, "0.5.36", now=2000.0)
    assert notify_engine.bridge_up(st, "0.5.36", now=2095.0) == (
        "bridge_restarted", {"version": "0.5.36", "down": "1 min 35 s", "update": ""})
    # the stop is used once: a later start without a clean stop is a plain start
    assert notify_engine.bridge_up(st, "0.5.36", now=3000.0)[0] == "bridge_started"


def test_restart_into_a_new_version_says_updated(tmp_path):
    st = MetricsStore(str(tmp_path / "m.db"))
    notify_engine.bridge_down(st, "0.5.35", now=0.0)
    ev, vals = notify_engine.bridge_up(st, "0.5.36", now=20.0)
    assert ev == "bridge_restarted" and vals["update"] == ", updated from 0.5.35"
    assert vals["down"] == "20 s"
    _, msg = notify_engine.actionable.templates().render("bridge_restarted", **vals)
    assert msg == "Bridge restarted (v0.5.36, updated from 0.5.35) after 20 s down."


def test_lifecycle_has_its_own_trigger_on_by_default(tmp_path):
    cfg = notify_engine.config(MetricsStore(str(tmp_path / "m.db")))
    assert cfg["triggers"]["bridge"]["enabled"] is True
    for ev in ("bridge_started", "bridge_restarted", "bridge_stopped"):
        assert notify_engine.TRIGGER[ev] == "bridge"
    cfg["triggers"]["bridge"]["enabled"] = False
    assert notify_engine.fire(None, "bridge_stopped", cfg=cfg, version="1") == 0


def test_app_sends_started_on_start_and_stopped_before_notifications_stop():
    up, down = APP.index("notify_engine.bridge_up("), APP.index("notify_engine.bridge_down(")
    assert APP.index("await actionable.start(") < up < APP.index("yield", up)
    stop = APP.index("await actionable.stop()")
    assert APP.index('"bridge_stopped"') < stop and down < stop


def test_shutdown_releases_the_battery_before_the_stop_notification():
    """Home Assistant kills an add-on 10 s after asking it to stop. A held dispatch is
    released first, and the stop notification may only take what is left (3 s at most)."""
    end = APP.index("await supervisor.stop_all()")
    block = APP[APP.index("finally:", APP.index("yield", APP.index("notify_engine.bridge_up("))):end]
    assert block.index('release_held("shutdown")') < block.index('"bridge_stopped"') \
        < block.index("await actionable.stop()")
    wait = block[block.index('"bridge_stopped"'):block.index("await actionable.stop()")]
    assert "version=__version__), 3)" in wait
