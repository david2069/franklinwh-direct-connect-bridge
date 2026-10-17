"""0.5.9: the Modbus client (this bridge) opens the Modbus TCP Server (aGate :502) only for
a real command, a deliberate check, or the hourly ratings read — never to show a status.

The Modbus TCP Server (aGate :502) serves one client at a time, and the Modbus Bridge holds
a long-lived session there. Before this batch the bridge connected on every poll (#221) and
for every open browser tab every 30 s (#223), and tried to reach a mock's :502 (#95). Release
reported "released" without reading the aGate back (#174).
"""
import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import app as app_module
from franklinwh_direct_connect_bridge import battery_control as bc
from franklinwh_direct_connect_bridge import client as client_mod
from franklinwh_direct_connect_bridge import poller
from franklinwh_direct_connect_bridge import state
from franklinwh_direct_connect_bridge.config import Settings


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.setattr(bc, "_ENABLED", True)
    monkeypatch.setattr(bc, "_LAST", {}, raising=False)
    monkeypatch.setattr(bc, "_HOST_OVERRIDE", "")
    monkeypatch.setattr(bc, "_RATINGS_CACHE", {})
    bc._clear_active()
    yield
    bc._clear_active()


class _Opened:
    """Counts every attempt to reach :502, by either route."""
    def __init__(self, monkeypatch):
        self.sockets, self.sessions = [], []
        monkeypatch.setattr(client_mod.discover, "port_open",
                            lambda h, p, timeout=0: self.sockets.append((h, p)) or True)

        def _connect(host):
            self.sessions.append(host)
            raise ConnectionError("test: no aGate")
        monkeypatch.setattr(bc, "_connect", _connect)


# -- #221: a poll opens nothing --------------------------------------------------------------
def test_summary_opens_no_502_socket(monkeypatch):
    opened = _Opened(monkeypatch)

    def _no_9000(*a, **kw):
        raise OSError("test: no aGate on :9000")
    monkeypatch.setattr(client_mod, "_client", _no_9000)
    for _ in range(5):
        out = client_mod.summary(Settings(), host="192.0.2.10")
    assert opened.sockets == [] and opened.sessions == []
    assert out["modbus_502"] is None and out["modbus_502_at"] is None


def test_summary_reports_the_last_real_result_with_its_time(monkeypatch):
    monkeypatch.setattr(client_mod, "_client", lambda *a, **kw: (_ for _ in ()).throw(OSError()))
    bc._record("192.0.2.10", "no_sunspec", "status", "no response")
    out = client_mod.summary(Settings(), host="192.0.2.10")
    assert out["modbus_502"] is True          # the socket opened; SunSpec did not answer
    assert out["modbus_502_at"] and out["modbus_502_source"] == "status"


def test_a_failed_connect_is_recorded_as_unreachable(monkeypatch):
    class _Ctl:
        def __init__(self, *a, **kw):
            pass

        def connect(self):
            return False
    monkeypatch.setattr(bc, "_lib", lambda: (_Ctl, object))
    with pytest.raises(ConnectionError):
        bc._connect("192.0.2.10")
    assert bc.last_result("192.0.2.10")["state"] == "unreachable"
    assert client_mod._probe_modbus("192.0.2.10") is False


# -- #221: the link history records each result once -----------------------------------------
class _Store:
    def __init__(self):
        self.rows = []

    def record_link_probe(self, gw_id, outcome, **kw):
        self.rows.append((gw_id, outcome, kw))


def test_link_leg_recorded_once_per_result(monkeypatch):
    monkeypatch.setattr(poller, "_MB_RECORDED", {}, raising=False)
    st = _Store()
    summ = {"modbus_502": True, "modbus_502_at": 1000.0}
    for _ in range(10):
        poller._record_modbus_leg(st, "gw1", summ)
    assert len(st.rows) == 1
    gw, outcome, kw = st.rows[0]
    assert outcome == "ok" and kw["now"] == 1000.0
    assert "expected_interval_s" not in kw    # sparse by design: gaps are not missed polls
    poller._record_modbus_leg(st, "gw1", {"modbus_502": False, "modbus_502_at": 2000.0})
    assert [r[1] for r in st.rows] == ["ok", "failed"]


def test_link_leg_not_recorded_when_not_measured(monkeypatch):
    monkeypatch.setattr(poller, "_MB_RECORDED", {}, raising=False)
    st = _Store()
    poller._record_modbus_leg(st, "gw1", {"modbus_502": None, "modbus_502_at": None})
    assert st.rows == []


# -- #223: an open browser tab costs nothing -------------------------------------------------
@pytest.fixture
def api(monkeypatch):
    calls = []
    monkeypatch.setenv("FWH_MODBUS_HOST", "192.0.2.10")
    monkeypatch.setattr(bc, "status", lambda host: calls.append(host) or
                        {"available": True, "state": "ready", "reason": "", "hint": "",
                         "max_charge_w": 5000, "max_discharge_w": 5000})
    now = [1_000_000.0]
    monkeypatch.setattr(app_module.time, "time", lambda: now[0])
    return TestClient(app_module.create_app()), calls, now


def test_battery_poll_connects_once_not_every_30s(api):
    c, calls, now = api
    for _ in range(40):                               # 40 polls 15 s apart = 10 minutes
        assert c.get("/api/battery/command").status_code == 200
        now[0] += 15
    assert len(calls) == 1, calls


def test_battery_poll_refreshes_after_an_hour(api):
    c, calls, now = api
    c.get("/api/battery/command")
    now[0] += 3601
    c.get("/api/battery/command")
    assert len(calls) == 2


def test_refresh_is_rate_limited(api):
    c, calls, now = api
    c.get("/api/battery/command")
    c.get("/api/battery/command?refresh=1")           # within 30 s: cached
    assert len(calls) == 1
    now[0] += 31
    d = c.get("/api/battery/command?refresh=1").json()
    assert len(calls) == 2 and d["checked_at"] == now[0]


def test_changing_the_modbus_setting_rechecks_once(api, monkeypatch):
    c, calls, now = api
    c.get("/api/battery/command")
    monkeypatch.setattr(app_module.db, "get_store", lambda s: None)
    c.put("/api/modbus", json={"enabled": True})
    c.get("/api/battery/command")
    c.get("/api/battery/command")
    assert len(calls) == 2


# -- #95: a mock gateway has no Modbus -------------------------------------------------------
@pytest.fixture
def mock_gw():
    state.register_gateway("mock-t95", "127.0.0.1:5555", is_mock=True)
    yield "127.0.0.1:5555"
    state.unregister_gateway("mock-t95")


def test_mock_is_never_connected(monkeypatch, mock_gw):
    opened = _Opened(monkeypatch)
    for host in (mock_gw, "127.0.0.1"):              # some callers drop the port
        cap = bc.capability(host)
        assert cap["state"] == "not_configured" and cap["reason"] == bc.MOCK_REASON
        assert bc.status(host)["reason"] == bc.MOCK_REASON
        assert bc.cached_ratings(host) == (None, None)
        assert bc.execute("Release", host=host)["result"] == bc.MOCK_REASON
    assert opened.sessions == []


def test_real_gateway_sharing_the_mock_address_is_still_reached(monkeypatch, mock_gw):
    state.register_gateway("emu-t95", "127.0.0.1:9000")
    try:
        assert not bc.is_mock_target("127.0.0.1")
        assert bc.is_mock_target(mock_gw)
    finally:
        state.unregister_gateway("emu-t95")


def test_an_explicit_override_is_never_treated_as_a_mock(monkeypatch, mock_gw):
    monkeypatch.setattr(bc, "_HOST_OVERRIDE", "192.0.2.20")
    assert not bc.is_mock_target(mock_gw)


# -- #174: Release reports what the aGate says -----------------------------------------------
class _Ctl:
    def __init__(self, *, still=False, readback_error=False):
        self.still, self.err, self.resets = still, readback_error, 0

    def reset_control_state(self):
        self.resets += 1

    def read_control_status(self):
        if self.err:
            raise OSError("timed out")
        return {"wset_enabled": self.still}


def _release_with(monkeypatch, ctl):
    monkeypatch.setattr(bc, "_connect", lambda host: (ctl, object))
    monkeypatch.setattr(bc, "_close", lambda c: None)
    return bc.execute("Release", host="192.0.2.10")


def test_release_confirmed_by_read_back(monkeypatch):
    out = _release_with(monkeypatch, _Ctl())
    assert out["ok"] and out["confirmed"] and out["result"] == "released"


def test_release_not_reported_when_the_agate_still_forces(monkeypatch):
    out = _release_with(monkeypatch, _Ctl(still=True))
    assert out["ok"] is False and "still reports" in out["result"]


def test_release_says_when_it_could_not_confirm(monkeypatch):
    out = _release_with(monkeypatch, _Ctl(readback_error=True))
    assert out["confirmed"] is False and "not confirmed" in out["result"]


def test_release_with_client_off_names_the_active_force(monkeypatch):
    with bc._lock:
        bc._active.update({"command": "Force Charge", "started": 0})
    monkeypatch.setattr(bc, "_ENABLED", False)
    out = bc.execute("Release", host="192.0.2.10")
    assert out["ok"] is False and "Force Charge" in out["result"]


# -- #88: the Modbus client is off for a new install ------------------------------------------
class _CfgStore:
    def __init__(self, cfg=None, gateways=()):
        self.cfg, self._gws = dict(cfg or {}), list(gateways)

    def get_config(self, key, default=None):
        return self.cfg.get(key, default)

    def set_config(self, key, value):
        self.cfg[key] = value

    def gateways(self):
        return self._gws


def test_new_install_starts_with_the_client_off_and_keeps_it():
    st = _CfgStore()
    assert app_module._modbus_client_enabled(st) is False
    assert st.cfg["modbus_enabled"] == "0"
    st._gws.append({"id": "gw1"})               # adding the first gateway changes nothing
    assert app_module._modbus_client_enabled(st) is False


def test_existing_install_that_never_set_it_stays_on():
    st = _CfgStore(gateways=[{"id": "gw1"}])
    assert app_module._modbus_client_enabled(st) is True
    assert st.cfg["modbus_enabled"] == "1"


@pytest.mark.parametrize("val,want", [("1", True), ("0", False)])
def test_an_explicit_choice_is_kept(val, want):
    assert app_module._modbus_client_enabled(_CfgStore({"modbus_enabled": val})) is want


def test_the_module_default_is_off():
    """Without a store (metrics off) nothing applies a setting: the default must be off."""
    import ast
    import pathlib
    tree = ast.parse(pathlib.Path(bc.__file__).read_text())
    vals = [n.value.value for n in tree.body if isinstance(n, ast.Assign)
            and any(getattr(t, "id", "") == "_ENABLED" for t in n.targets)]
    assert vals == [False]
