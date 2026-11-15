"""#426 — a poll the aGate refuses (result:1) is a failed poll, not a healthy blank one.

The 1101 login and the 1301 power-flow read came back {"opt":0,"result":1,"reason":7};
summary() set ok:True after login and read every value from the refusal, so the gateway
showed healthy with blank telemetry and nothing was logged."""
from franklinwh_direct_connect_bridge import client as client_mod
from franklinwh_direct_connect_bridge import config

REFUSED = {"opt": 0, "result": 1, "reason": 7}
MANIFEST = {"opt": 0, "result": 0, "IBG_SN": "TESTSERIAL01", "IBG_VER": "V1", "APP_VER": "A1",
            "protocolVer": "V1.12.02"}
PF = {"opt": 0, "result": 0, "soc": 55, "p_uti": 100, "p_sun": 0, "p_fhp": -200,
      "p_load": 300, "name": "Self-Consumption", "run_status": 1}


class _Fake:
    def __init__(self, login=MANIFEST, pf=PF):
        self._login, self._pf = login, pf

    def __enter__(self): return self
    def __exit__(self, *a): return False
    def login(self): return dict(self._login)
    def power_flow(self): return dict(self._pf)
    def mode_list(self): return {"current_id": 1, "list": []}
    def der_comms(self): return {}
    def smart_circuits(self): return {}
    def ibg_run_status(self): return {}
    def offgrid(self): return {}


def _summary(monkeypatch, fake):
    monkeypatch.setattr(client_mod, "_client", lambda s, host=None: fake)
    monkeypatch.setattr(client_mod.discover, "ping", lambda h, timeout=1.0: True)
    return client_mod.summary(config.get_settings(), "192.0.2.10")


def test_a_good_poll_is_ok(monkeypatch):
    out = _summary(monkeypatch, _Fake())
    assert out["ok"] is True and out["power"]["soc"] == 55 and not out.get("error")


def test_refused_power_flow_is_a_failed_poll_with_the_reason(monkeypatch):
    out = _summary(monkeypatch, _Fake(pf=REFUSED))
    assert out["ok"] is False
    assert "result 1" in out["error"] and "reason 7" in out["error"] and "1301" in out["error"]
    assert "power" not in out            # no blank telemetry passed off as a reading


def test_refused_login_is_a_failed_poll_with_the_reason(monkeypatch):
    out = _summary(monkeypatch, _Fake(login=REFUSED))
    assert out["ok"] is False
    assert "login" in out["error"] and "result 1" in out["error"] and "reason 7" in out["error"]
    assert "power" not in out
