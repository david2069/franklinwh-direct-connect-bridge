"""Off-grid, owner 2026-11-13: the off-grid SoC is the SoC at which a USER-REQUESTED
off-grid returns to the grid (not a floor the battery holds); the OFF-GRID pill opens a
modal (state, off-grid for, stored kWh, time left; Reconnect when user requested); while
the aGate switches, the dialog says it is waiting, shows the aGate dropping offline and
coming back, and a push says when it is done."""
import pathlib

from franklinwh_direct_connect_bridge import notify_engine

PKG = pathlib.Path(__file__).resolve().parents[1] / "src" / "franklinwh_direct_connect_bridge"
JS = (PKG / "static" / "js" / "app.js").read_text()
APP = (PKG / "app.py").read_text()
TOP = (PKG / "templates" / "partials" / "topbar.html").read_text()
IDX = (PKG / "templates" / "index.html").read_text()
CTL = (PKG / "templates" / "tabs" / "control.html").read_text()


def _p(soc, kind, load=2000, solar=0, reconnect=5):
    return {"off_grid": True, "off_grid_kind": kind, "soc": soc, "load_w": load,
            "solar_w": solar, "offgrid_reconnect_soc": reconnect}


def test_user_requested_runs_to_the_reconnect_soc():
    # (35.7 − 5)% of 13.6 kWh = 4.18 kWh at 2.0 kW = 2 h 5 min; stored = 35.7% = 4.9 kWh
    assert notify_engine.off_grid_metrics(_p(35.7, "simulated"), 13.6) == (
        "SoC 36%, stored 4.9 kWh, home 2.0 kW — about 2 h 5 min until it reconnects to "
        "the grid at 5%")
    assert notify_engine.off_grid_metrics(_p(4, "simulated"), 13.6).endswith(
        "— reconnecting to the grid at 5%")


def test_outage_runs_to_empty():
    assert notify_engine.off_grid_metrics(_p(80, "outage"), 13.6) == (
        "SoC 80%, stored 10.9 kWh, home 2.0 kW — about 5 h 26 min left at current usage")


def test_no_floor_wording():
    for text in (JS, CTL):
        assert "restore floor" not in text and "Restore SoC floor" not in text
    assert "Reconnect SoC" in CTL
    assert "returns to the grid when the battery reaches" in JS


def test_status_route_and_pill_modal():
    assert '@app.get("/api/offgrid/status")' in APP
    assert 'data-testid="offgrid-pill"' in TOP and "openOffgridModal()" in TOP
    for tid in ("offgrid-modal", "offgrid-row", "offgrid-for", "offgrid-metrics",
                "offgrid-reconnect"):
        assert f'data-testid="{tid}"' in IDX


def test_waiting_lines_and_push_hint():
    track = JS[JS.index("async trackCommand("):JS.index("closeCmdProgress()")]
    assert "Waiting for the aGate to respond" in track
    assert "aGate offline" in track and "aGate online again" in track
    assert "notifyWhenDone" in track


def test_status_endpoint(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from franklinwh_direct_connect_bridge import app as app_module, state, config, environment, db
    from franklinwh_direct_connect_bridge.db import MetricsStore
    from franklinwh_direct_connect_bridge import constants
    store = MetricsStore(str(tmp_path / "m.db"))
    constants.update(store, {"battery_capacity_kwh": 13.6})
    monkeypatch.setattr(environment, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "_settings", None)
    monkeypatch.setattr(db, "get_store", lambda s: store)
    c = TestClient(app_module.create_app())
    # A private registry, put back afterwards: other tests read the gateways create_app made.
    monkeypatch.setattr(state, "_gateways", {})
    monkeypatch.setattr(state, "_default_id", None)
    gw = state.register_gateway("g1", "127.0.0.1:1", "House")
    gw.last_summary = {"ok": True, "power": _p(35.7, "simulated")}
    gw.last_state = {"off_grid": True, "off_grid_since": 1000.0}
    state.register_gateway("g2", "127.0.0.1:2", "Garage").last_summary = {
        "ok": True, "power": {"off_grid": False, "soc": 80}}
    rows = c.get("/api/offgrid/status").json()["gateways"]
    assert [r["id"] for r in rows] == ["g1"]
    r = rows[0]
    assert r["label"] == "House" and r["kind"] == "simulated" and r["reason"] == "user requested"
    assert r["since"] == 1000.0 and r["reconnect_soc"] == 5
    assert "until it reconnects to the grid at 5%" in r["metrics"]
    assert "notify" in c.get("/api/offgrid/status").json()
