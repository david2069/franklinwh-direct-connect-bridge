"""Forces act on their own gateway: Battery Control (#349), the host override (#354), and
each force's own SoC reader and event sink (#355)."""
import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import app as app_module
from franklinwh_direct_connect_bridge import battery_control as bc
from franklinwh_direct_connect_bridge import client as client_module
from franklinwh_direct_connect_bridge import db, state


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    state.reset_gateways()
    bc._clear_active()
    bc.set_host_override("")
    monkeypatch.delenv("FWH_MODBUS_HOST", raising=False)
    monkeypatch.setattr(bc, "_watchdog_loop", lambda *a, **k: None)   # no real threads
    yield
    bc._clear_active()
    bc.set_host_override("")
    state.reset_gateways()


def _two_gateways():
    a = state.register_gateway("gw-a", "10.0.0.1", "A")
    b = state.register_gateway("gw-b", "10.0.0.2", "B")
    a.last_state, b.last_state = {"soc": 40}, {"soc": 80}
    state.set_default("gw-a")
    return a, b


# ── #355 ─────────────────────────────────────────────────────────────────────

class _Ctl:
    """A controller whose send_command can run a second force mid-flight."""
    during_send = None

    def send_command(self, cmd, dry_run=False):
        if _Ctl.during_send:
            f, _Ctl.during_send = _Ctl.during_send, None
            f()
        return True, "sent"

    def reset_control_state(self):
        pass

    def read_control_status(self):
        return {"wset_enabled": 0}

    def disconnect(self):
        pass


def test_a_force_keeps_its_own_soc_reader_when_another_arms_meanwhile(monkeypatch):
    monkeypatch.setattr(bc, "capability", lambda h: {"ready": True, "state": "ready",
                                                     "reason": "", "hint": ""})
    monkeypatch.setattr(bc, "_connect", lambda h: (_Ctl(), lambda power_watts: power_watts))
    monkeypatch.setattr(bc, "_ratings", lambda c: (5000, 5000))
    sinks = {"a": [], "b": []}
    # While A's command is on the wire, B's force runs start to finish.
    _Ctl.during_send = lambda: bc.execute(
        "Force Discharge", host="10.0.0.2", power_w=1000, power_mode="w",
        soc_getter=lambda: 80, on_event=lambda s, d: sinks["b"].append(s))
    bc.execute("Force Charge", host="10.0.0.1", power_w=1000, power_mode="w",
               soc_getter=lambda: 40, on_event=lambda s, d: sinks["a"].append(s))
    assert bc._active["10.0.0.1"]["soc_getter"]() == 40
    assert bc._active["10.0.0.2"]["soc_getter"]() == 80
    assert sinks == {"a": ["dispatch-start"], "b": ["dispatch-start"]}


# ── #354 ─────────────────────────────────────────────────────────────────────

def test_the_host_override_applies_to_the_default_gateway_only():
    _two_gateways()
    bc.set_host_override("192.0.2.50")
    assert bc.effective_target("10.0.0.1") == ("192.0.2.50", 502)
    assert bc.effective_target("10.0.0.2") == ("10.0.0.2", 502)


def test_fwh_modbus_host_is_no_longer_read(monkeypatch):
    """#379: every gateway's Modbus client connects to its own host."""
    _two_gateways()
    monkeypatch.setenv("FWH_MODBUS_HOST", "192.0.2.60")
    assert bc.effective_target("10.0.0.1") == ("10.0.0.1", 502)
    assert bc.effective_target("10.0.0.2") == ("10.0.0.2", 502)


def test_with_one_gateway_the_override_still_applies():
    state.register_gateway("gw-a", "10.0.0.1", "A")
    bc.set_host_override("192.0.2.60")
    assert bc.effective_target("10.0.0.1") == ("192.0.2.60", 502)


# ── #349 ─────────────────────────────────────────────────────────────────────

@pytest.fixture
def api(tmp_path, monkeypatch):
    st = db.MetricsStore(str(tmp_path / "m.db"))
    monkeypatch.setattr(db, "get_store", lambda *a, **k: st)
    monkeypatch.setattr(client_module, "writes_enabled", lambda s: True)
    c = TestClient(app_module.create_app())
    _two_gateways()          # after create_app: its lifespan isn't run by a bare client
    sent = []

    def _exec(cmd, *, host, soc_getter=None, on_event=None, **kw):
        sent.append((cmd, host, soc_getter() if soc_getter else None))
        if cmd.startswith("Force"):
            bc._arm_watchdog(host, cmd, -1000, 0, 0, soc_getter=soc_getter, on_event=on_event)
        else:
            bc._clear_active(host)
        return {"ok": True, "result": "ok", "active": cmd if cmd.startswith("Force") else "Not Active"}
    monkeypatch.setattr(bc, "execute", _exec)
    monkeypatch.setattr(bc, "status", lambda h: {"available": True, "state": "ready"})
    return c, st, sent


def _force(c, gateway=None, value="Force Discharge"):
    q = f"?gateway={gateway}" if gateway else ""
    return c.post("/api/battery/command" + q, json={"slug": "battery_command", "value": value})


def test_battery_control_forces_the_gateway_on_screen(api):
    c, st, sent = api
    assert _force(c, "gw-b").json()["ok"] is True
    assert sent == [("Force Discharge", "10.0.0.2", 80)]        # B's host and B's SoC
    assert [d["gateway_id"] for d in st.active_dispatches()] == ["gw-b"]


def test_battery_control_without_a_gateway_is_refused(api):
    """No default-gateway fallback any more (#379): an unnamed force is a 400, nothing sent."""
    c, st, sent = api
    assert _force(c).status_code == 400
    assert sent == []


def test_each_gateway_shows_its_own_force_and_the_site_lists_them(api):
    c, st, sent = api
    _force(c, "gw-b")
    assert c.get("/api/battery/command?gateway=gw-b").json()["active"] == "Force Discharge"
    d = c.get("/api/battery/command?gateway=gw-a").json()
    assert d["active"] == "Not Active"
    assert [(h["gateway_id"], h["active"]) for h in d["held"]] == [("gw-b", "Force Discharge")]


def test_release_on_one_gateway_leaves_the_other(api):
    c, st, sent = api
    _force(c, "gw-a")
    _force(c, "gw-b")
    _force(c, "gw-b", "Release")
    assert sent[-1] == ("Release", "10.0.0.2", 80)
    assert bc.held_hosts() == ["10.0.0.1"]
