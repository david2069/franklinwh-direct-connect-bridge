"""Off-grid notification carries the battery metrics and how long it will last at the
current usage (owner 2026-11-13: the FranklinWH app sends one, on historical usage)."""
import pathlib

from franklinwh_direct_connect_bridge import notify_engine

POLLER = pathlib.Path(notify_engine.__file__).with_name("poller.py").read_text()


def _snap(off_grid=False, soc=80, load=2000, solar=0, gen=0):
    return {"ok": True, "power": {"off_grid": off_grid, "off_grid_kind": "outage", "soc": soc,
                                  "load_w": load, "solar_w": solar, "generator_w": gen}}


def _fire(snap, cap):
    return notify_engine.evaluate(snap, _snap(), notify_engine.config(None), capacity_kwh=cap)


def test_runtime_at_current_usage():
    # 80% of 13.6 kWh = 10.88 kWh at 2.0 kW net = 5 h 26 min
    assert _fire(_snap(True), 13.6) == [("off_grid", {
        "reason": "grid outage",
        "metrics": "SoC 80%, home 2.0 kW — about 5 h 26 min left at current usage"})]


def test_solar_net_of_load():
    ev = _fire(_snap(True, load=2000, solar=1500), 13.6)[0][1]
    assert ev["metrics"] == ("SoC 80%, home 2.0 kW, solar 1.5 kW — "
                             "about 21 h 46 min left at current usage")


def test_solar_covers_home():
    ev = _fire(_snap(True, load=800, solar=1500), 13.6)[0][1]
    assert ev["metrics"] == "SoC 80%, home 0.8 kW, solar 1.5 kW — solar is covering the home"


def test_no_capacity_no_estimate():
    ev = _fire(_snap(True), None)[0][1]
    assert ev["metrics"] == ("SoC 80%, home 2.0 kW — set Battery capacity (Automation) "
                             "for a runtime estimate")


def test_message_and_poller_passes_capacity():
    _, msg = notify_engine.actionable.templates().render(
        "off_grid", gateway="Home", reason="grid outage",
        metrics="SoC 80%, home 2.0 kW — about 5 h 26 min left at current usage")
    assert msg == ("Gateway went OFF-GRID [Home] (grid outage) — running on battery: "
                   "SoC 80%, home 2.0 kW — about 5 h 26 min left at current usage.")
    assert "capacity_kwh=" in POLLER
