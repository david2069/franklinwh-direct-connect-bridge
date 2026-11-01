"""One stored default gateway (#182, #146), and a disable releases that gateway's force (#353)."""
import os
import re

import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import app as app_module
from franklinwh_direct_connect_bridge import battery_control as bc
from franklinwh_direct_connect_bridge import client as client_module
from franklinwh_direct_connect_bridge import db, mockgw, state, supervisor

TEMPLATES = os.path.join(os.path.dirname(__file__), "..", "src",
                         "franklinwh_direct_connect_bridge", "templates")


@pytest.fixture(autouse=True)
def _fresh():
    state.reset_gateways()
    yield
    state.reset_gateways()


@pytest.fixture
def st(tmp_path):
    return db.MetricsStore(str(tmp_path / "m.db"))


@pytest.fixture
def c(st, monkeypatch):
    monkeypatch.setattr(db, "get_store", lambda *a, **k: st)

    async def _noop(*a, **k):
        return None
    monkeypatch.setattr(supervisor, "start_poller", _noop)
    monkeypatch.setattr(supervisor, "stop_poller", _noop)
    monkeypatch.setattr(supervisor, "is_running", lambda gid: False)
    monkeypatch.setattr(mockgw, "start_mock", lambda gid, **k: "127.0.0.1:59999")
    monkeypatch.setattr(mockgw, "stop_mock", lambda gid: None)
    monkeypatch.setattr(client_module, "writes_enabled", lambda s: True)
    return TestClient(app_module.create_app())


def _add(c, label, host):
    r = c.post("/api/gateways", json={"label": label, "host": host})
    assert r.status_code == 201, r.text
    return r.json()["id"]


# ── the stored default is the default ───────────────────────────────────────

def test_editing_the_default_gateway_keeps_it_the_default(c):
    a, b = _add(c, "A", "10.0.0.1"), _add(c, "B", "10.0.0.2")
    assert state.default_gateway().id == a
    assert c.patch(f"/api/gateways/{a}", json={"label": "A2"}).status_code == 200
    assert state.default_gateway().id == a          # re-registering moved A to the end


def test_the_first_gateway_is_the_default_and_a_second_default_is_refused(c, st):
    a = _add(c, "A", "10.0.0.1")
    assert st.gateway(a)["is_default"] == 1
    r = c.post("/api/gateways", json={"label": "B", "host": "10.0.0.2", "is_default": True})
    assert r.status_code == 409 and "'A' is the default" in r.json()["detail"]
    b = _add(c, "B", "10.0.0.2")
    r = c.patch(f"/api/gateways/{b}", json={"is_default": True})
    assert r.status_code == 409 and "Make default" in r.json()["detail"]
    assert c.patch(f"/api/gateways/{a}", json={"is_default": False}).status_code == 409


def test_make_default_is_the_only_way_the_default_moves(c, st):
    a, b = _add(c, "A", "10.0.0.1"), _add(c, "B", "10.0.0.2")
    r = c.post(f"/api/gateways/{b}/default")
    assert r.status_code == 200 and r.json()["is_default"] is True
    assert st.gateway(a)["is_default"] == 0 and state.default_gateway().id == b


def test_the_default_cant_be_disabled_and_an_enabled_gateway_cant_be_deleted(c):
    a, b = _add(c, "A", "10.0.0.1"), _add(c, "B", "10.0.0.2")
    r = c.patch(f"/api/gateways/{a}", json={"enabled": False})
    assert r.status_code == 409 and "can't be disabled" in r.json()["detail"]
    r = c.delete(f"/api/gateways/{b}")
    assert r.status_code == 409 and "Disable it first" in r.json()["detail"]
    assert c.patch(f"/api/gateways/{b}", json={"enabled": False}).status_code == 200
    assert c.delete(f"/api/gateways/{b}").status_code == 200
    r = c.post(f"/api/gateways/{a}/default")
    assert r.status_code == 200


def test_a_disabled_gateway_cant_be_made_the_default(c):
    a, b = _add(c, "A", "10.0.0.1"), _add(c, "B", "10.0.0.2")
    c.patch(f"/api/gateways/{b}", json={"enabled": False})
    r = c.post(f"/api/gateways/{b}/default")
    assert r.status_code == 409 and "Enable it first" in r.json()["detail"]


# ── migration: exactly one default, the one boot used until now ─────────────

def test_migration_marks_the_gateway_boot_made_the_default(st):
    st.create_gateway(gw_id="z", label="Zed", host="10.0.0.9")
    st.create_gateway(gw_id="m", label="Alpha mock", is_mock=True, enabled=False)
    st.create_gateway(gw_id="b", label="Bravo", host="10.0.0.2")
    assert st.ensure_one_default() == "b"          # first ENABLED row by label
    assert [r["id"] for r in st.gateways() if r["is_default"]] == ["b"]


def test_migration_moves_a_flag_off_a_disabled_gateway(st):
    st.create_gateway(gw_id="d", label="Dead", host="10.0.0.1", is_default=True, enabled=False)
    st.create_gateway(gw_id="l", label="Live", host="10.0.0.2")
    assert st.ensure_one_default() == "l"
    assert st.ensure_one_default() == "l"          # idempotent


def test_migration_keeps_a_valid_default(st):
    st.create_gateway(gw_id="a", label="A", host="10.0.0.1")
    st.create_gateway(gw_id="b", label="B", host="10.0.0.2", is_default=True)
    assert st.ensure_one_default() == "b"


# ── #353: disabling releases this bridge's force on that gateway first ─────

def test_disabling_a_gateway_releases_its_force_first(c, st, monkeypatch):
    a, b = _add(c, "A", "10.0.0.1"), _add(c, "B", "10.0.0.2")
    st.record_dispatch(schedule_id="s", name="s", gateway_id=b, host="10.0.0.2",
                       direction="charge", watts=1000, power_mode="w", target_soc=90,
                       window_start_ts=1, window_end_ts=None)
    sent = []
    monkeypatch.setattr(bc, "execute", lambda cmd, **kw: (sent.append((cmd, kw.get("host"))), {
        "ok": True, "result": "released"})[1])
    r = c.patch(f"/api/gateways/{b}", json={"enabled": False})
    assert r.status_code == 200 and r.json()["released"] == "released"
    assert sent == [("Release", "10.0.0.2")]
    assert st.active_dispatches() == []


def test_a_failed_release_leaves_the_gateway_enabled(c, st, monkeypatch):
    a, b = _add(c, "A", "10.0.0.1"), _add(c, "B", "10.0.0.2")
    st.record_dispatch(schedule_id="s", name="s", gateway_id=b, host="10.0.0.2",
                       direction="charge", watts=1000, power_mode="w", target_soc=90,
                       window_start_ts=1, window_end_ts=None)
    monkeypatch.setattr(bc, "execute", lambda cmd, **kw: {"ok": False, "result": "timeout"})
    r = c.patch(f"/api/gateways/{b}", json={"enabled": False})
    assert r.status_code == 502 and "was not disabled" in r.json()["detail"]
    assert st.gateway(b)["enabled"] == 1 and len(st.active_dispatches()) == 1


def test_disabling_with_no_force_sends_nothing(c, monkeypatch):
    a, b = _add(c, "A", "10.0.0.1"), _add(c, "B", "10.0.0.2")
    monkeypatch.setattr(bc, "execute", lambda *a, **k: pytest.fail("no release expected"))
    r = c.patch(f"/api/gateways/{b}", json={"enabled": False})
    assert r.status_code == 200 and "released" not in r.json()


# ── #146: the confirm dialog opens above the Edit dialog ───────────────────

def test_confirm_dialog_stacks_above_the_gateway_edit_dialog():
    idx = open(os.path.join(TEMPLATES, "index.html")).read()
    conf = re.search(r'confirmState\.open" x-cloak\s+class="fixed inset-0 z-\[(\d+)\]', idx)
    sett = open(os.path.join(TEMPLATES, "tabs", "settings.html")).read()
    edit = re.search(r'gwEdit\.open" x-cloak class="fixed inset-0 z-\[(\d+)\]', sett)
    assert int(conf.group(1)) > int(edit.group(1))
