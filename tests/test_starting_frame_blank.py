"""#309 — the aGate's all-zero start-up frames after a reconnect are not readings.

HA Live 2026-10-23, after a Wi-Fi outage: 1301 read 0 for SoC and every flow for about two
minutes. The dashboard showed 0 W, history recorded five samples of 0 W, and MQTT sent 0
to Home Assistant. These values are now blanked, not recorded and not published, and the
poller logs when the frames start and when real readings return.
"""
import asyncio
import logging

from franklinwh_direct_connect_bridge import config, poller
from franklinwh_direct_connect_bridge.client import _apply_off_grid
from franklinwh_direct_connect_bridge.state import GatewayState


def _starting_summary():
    return {
        "ok": True,
        "power": {"soc": 0, "grid_w": 0, "solar_w": 0, "battery_w": 0, "load_w": 0,
                  "generator_w": 0, "run_status": 0, "run_status_desc": "Standby",
                  "kwh_sun": 0, "kwh_load": 0, "main_sw": [0, 0, 0]},
        "battery": {"soc": 0, "t_amb": 0, "run_status": 0, "run_status_desc": "Standby",
                    "modules": [{"sn": "A1", "soc": 91, "power_kw": 0.19}]},
        "energy_today": {"solar": 0, "home": 0},
        "tou_tiers": {"peak": [0, 0]},
        "relays": {"mainRelay1Status": 0, "mainRelay2Status": 0},
    }


def _real_summary():
    return {"ok": True, "power": {"soc": 90, "grid_w": 120, "solar_w": 0, "battery_w": 200,
                                  "load_w": 320, "run_status": 2}}


def test_every_value_of_the_frame_is_blanked():
    out = _starting_summary()
    _apply_off_grid(out)
    p = out["power"]
    assert p["agate_starting"] is True and p["off_grid"] is False
    for k in ("soc", "grid_w", "solar_w", "battery_w", "load_w", "generator_w",
              "run_status_desc", "kwh_sun", "kwh_load"):
        assert p[k] is None, k
    b = out["battery"]
    assert b["soc"] is None and b["t_amb"] is None and b["run_status_desc"] is None
    assert b["modules"] == [{"sn": "A1", "soc": 91, "power_kw": 0.19}]   # real; kept
    assert out["energy_today"] == {"solar": None, "home": None}
    assert out["tou_tiers"] is None


def test_a_real_zero_is_not_blanked():
    """A real frame with 0 W solar at night keeps its values: only the all-zero frame
    (SoC 0 too) is the start-up frame."""
    out = {"ok": True, "power": {"soc": 55, "grid_w": 0, "solar_w": 0, "battery_w": 0,
                                 "load_w": 0, "run_status": 0, "main_sw": [1, 0, 0]}}
    _apply_off_grid(out)
    assert not out["power"].get("agate_starting")
    assert out["power"]["solar_w"] == 0 and out["power"]["soc"] == 55


class _FakePub:
    states: list = []

    def __init__(self, settings, node, device, **k):
        self.configs = []

    def start(self): pass
    def stop(self): pass
    def is_connected(self): return True
    def publish_alerts(self, payload): pass
    def publish_state(self, st): _FakePub.states.append(dict(st))
    def publish_availability(self, online): pass


class _FakeStore:
    def __init__(self):
        self.inserted = []

    def insert(self, st, ts, serial, tiers=None, poll=None):
        self.inserted.append(dict(st))

    def prune(self, *a, **k):
        return 0

    def __getattr__(self, name):          # link history, alerts etc.: accept and ignore
        return lambda *a, **k: None


def _run(monkeypatch, frames):
    _FakePub.states = []
    store = _FakeStore()
    seq = iter(frames)

    def _summary(*a, **k):
        try:
            out = next(seq)()
        except StopIteration:
            out = _real_summary()
        _apply_off_grid(out)
        return out

    s = config.get_settings()
    monkeypatch.setattr(s, "mqtt_enabled", True)
    monkeypatch.setattr(s, "poll_interval", 1)
    monkeypatch.setattr(poller, "MqttPublisher", _FakePub)
    monkeypatch.setattr(poller, "metrics_active", lambda *_: True)
    monkeypatch.setattr(poller, "get_store", lambda *_: store)
    monkeypatch.setattr(poller.client, "firmware", lambda *a, **k: {"IBG_SN": "SN309", "IBG_VER": "V1"})
    monkeypatch.setattr(poller.client, "summary", _summary)
    import franklinwh_direct_connect_bridge.ha_supervisor as hs
    monkeypatch.setattr(hs, "apply_supervisor_mqtt", lambda *a, **k: None)
    gw = GatewayState(id="g309", label="mock", is_mock=True, publish_ha=True,
                      configured_host="127.0.0.1:1", active_host="127.0.0.1:1")

    async def go():
        stop = asyncio.Event()
        t = asyncio.create_task(poller.run_gateway(s, gw, stop))
        await asyncio.sleep(3.5)              # three or four polls at a 1 s interval
        stop.set()
        await asyncio.wait_for(t, timeout=10)
    asyncio.run(go())
    return store, gw


def test_start_up_frames_are_not_recorded_or_published(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger=poller.log.name)
    store, gw = _run(monkeypatch, [_starting_summary, _starting_summary])
    # Only real frames reached history and MQTT; none of them carries a 0 W from the frame.
    assert store.inserted and _FakePub.states
    assert all(r.get("soc") == 90 for r in store.inserted)
    assert all(r.get("soc") == 90 for r in _FakePub.states)
    msgs = [r.getMessage() for r in caplog.records]
    assert sum("aGate reconnecting" in m for m in msgs) == 1          # once, not per frame
    assert sum("aGate readings returned" in m for m in msgs) == 1


def test_the_dashboard_gets_the_blanked_frame(monkeypatch):
    """The UI reads gw.last_state: during the frames it must carry the flag and no 0 W."""
    seen = []
    orig = poller.entities.state_payload

    def spy(summ):
        st = orig(summ)
        seen.append(dict(st))
        return st
    monkeypatch.setattr(poller.entities, "state_payload", spy)
    _run(monkeypatch, [_starting_summary])
    first = seen[0]
    assert first["agate_starting"] is True
    assert first["grid_w"] is None and first["battery_w"] is None and first["soc"] is None
    assert "battery_status" not in first          # no "standby" derived from a blank
