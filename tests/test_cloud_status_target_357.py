"""Cloud status lands on the gateway whose serial was polled, read each pass (#357)."""
from franklinwh_direct_connect_bridge import cloud_status, state
from franklinwh_direct_connect_bridge.config import Settings
from franklinwh_direct_connect_bridge.state import GatewayState


def _gw(gid, serial):
    return GatewayState(id=gid, configured_host="", active_host="", label=gid,
                        serial=serial, serial_locked=True)


def _settings(serial):
    return Settings(fwh_cloud_email="e", fwh_cloud_password="p", fwh_cloud_gateway=serial)


def test_a_changed_cloud_gateway_is_reported_on_the_new_one(monkeypatch):
    a, b = _gw("gw-a", "AAAA0001"), _gw("gw-b", "BBBB0002")
    monkeypatch.setitem(state._gateways, "gw-a", a)
    monkeypatch.setitem(state._gateways, "gw-b", b)
    polled = []

    def fake_poll(s):
        polled.append(s.fwh_cloud_gateway)
        return {"is_vpp": s.fwh_cloud_gateway == "bbbb0002", "effective_mode": "Self",
                "programme": 9, "ts": len(polled)}

    monkeypatch.setattr(cloud_status, "poll", fake_poll)
    _, t1 = cloud_status.poll_and_attach(_settings("AAAA0001"))
    _, t2 = cloud_status.poll_and_attach(_settings("bbbb0002"))   # changed in Settings
    assert (t1, t2) == (a, b)
    assert (a.cloud_vpp, a.cloud_ts) == (False, 1), "the old gateway keeps its own status"
    assert (b.cloud_vpp, b.cloud_ts) == (True, 2)


def test_no_matching_gateway_attaches_nothing(monkeypatch):
    a = _gw("gw-a", "AAAA0001")
    monkeypatch.setitem(state._gateways, "gw-a", a)
    monkeypatch.setattr(cloud_status, "poll", lambda s: {"is_vpp": True, "ts": 1})
    data, target = cloud_status.poll_and_attach(_settings("ZZZZ9999"))
    assert data and target is None and a.cloud_ts == 0.0


def test_the_cloud_loop_reads_the_serial_each_pass():
    import inspect
    from franklinwh_direct_connect_bridge import app
    src = inspect.getsource(app)
    loop = src[src.index("def _cloud_status_loop"):src.index("_th.Thread(target=_cloud_status_loop")]
    assert "cloud_status.poll_and_attach(get_settings())" in loop
    assert "fwh_cloud_gateway" not in loop, "no serial frozen at loop start"
