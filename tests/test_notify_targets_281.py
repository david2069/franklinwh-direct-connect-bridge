"""#281: the target card. Devices carry a kind; Discover returns friendly names and kinds;
each trigger sends to a target ({type: all} or {type: device, ids}); Send test goes to the
devices chosen and never reports a bare "sent to 0"."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import app as app_module, ha_instances, notify_engine
from franklinwh_direct_connect_bridge.db import MetricsStore


@pytest.fixture
def st(tmp_path, monkeypatch):
    from franklinwh_direct_connect_bridge import db
    s = MetricsStore(str(tmp_path / "m.db"))
    monkeypatch.setattr(db, "get_store", lambda _s: s)
    s.create_ha_instance(ha_id="ha1", name="Home", base_url="http://ha.test", token="t")
    return s


def _two_devices(st):
    st.create_notify_device(dev_id="d1", alias="Phone", instance_id="ha1",
                            service="notify.mobile_app_phone", kind="phone")
    st.create_notify_device(dev_id="d2", alias="Tablet", instance_id="ha1",
                            service="notify.mobile_app_tab", kind="tablet")


def _html():
    return (Path(notify_engine.__file__).parent / "templates/tabs/settings.html").read_text()


# ── the device record ────────────────────────────────────────────────────────────────
def test_a_device_has_a_kind_and_a_user_id_for_later(st):
    st.create_notify_device(dev_id="d1", alias="Phone", instance_id="ha1",
                            service="notify.mobile_app_phone", kind="phone")
    d = st.notify_device("d1")
    assert d["kind"] == "phone" and "user_id" in d and d["user_id"] is None
    assert st.update_notify_device("d1", kind="tablet")["kind"] == "tablet"


def test_adding_a_device_without_a_kind_derives_it(st):
    c = TestClient(app_module.create_app())
    r = c.post("/api/ha/notify-devices", json={"alias": "Lounge", "instance_id": "ha1",
                                              "service": "notify.lounge_tv"})
    assert r.status_code == 201 and r.json()["kind"] == "tv"
    bad = c.post("/api/ha/notify-devices", json={"alias": "x", "instance_id": "ha1",
                                                "service": "notify.x", "kind": "car"})
    assert bad.status_code == 422


@pytest.mark.parametrize("service,name,kind", [
    ("notify.mobile_app_pixel_7", "", "phone"),
    ("notify.mobile_app_sams_ipad", "", "tablet"),
    ("notify.living_room_tv", "", "tv"),
    ("notify.alexa_media_kitchen", "Kitchen Echo", "speaker"),
    ("notify.email", "", "other"),
])
def test_kind_from_service_and_name(service, name, kind):
    assert notify_engine.kind_of(service, name) == kind


def test_discover_returns_friendly_names_and_kinds(st, monkeypatch):
    monkeypatch.setattr(ha_instances, "notify_targets",
                        lambda url, tok: ["notify.mobile_app_sams_iphone", "notify.living_room_tv"])
    monkeypatch.setattr(ha_instances, "states", lambda url, tok: [
        {"entity_id": "notify.mobile_app_sams_iphone",
         "attributes": {"friendly_name": "Sam's iPhone 15 Pro"}}])
    t = {x["service"]: x for x in
         TestClient(app_module.create_app()).get("/api/ha/notify-targets").json()["targets"]}
    assert t["notify.mobile_app_sams_iphone"]["friendly_name"] == "Sam's iPhone 15 Pro"
    assert t["notify.mobile_app_sams_iphone"]["kind"] == "phone"
    assert t["notify.living_room_tv"]["friendly_name"] == "Living Room Tv"
    assert t["notify.living_room_tv"]["kind"] == "tv"


# ── the target model ─────────────────────────────────────────────────────────────────
def test_a_trigger_defaults_to_all_and_stores_a_device_target(st):
    _two_devices(st)
    assert notify_engine.config(st)["triggers"]["off_grid"]["target"] == {"type": "all"}
    c = TestClient(app_module.create_app())
    put = c.put("/api/notify/triggers",
                json={"triggers": {"off_grid": {"target": {"type": "device", "ids": ["d2"]}}}})
    assert put.status_code == 200
    assert st.alert_targets() == {"off_grid": {"type": "device", "ids": ["d2"]}}
    got = c.get("/api/notify/triggers").json()["config"]["triggers"]["off_grid"]["target"]
    assert got == {"type": "device", "ids": ["d2"]}
    c.put("/api/notify/triggers", json={"triggers": {"off_grid": {"target": {"type": "all"}}}})
    assert st.alert_targets() == {}


def test_roles_are_not_a_target_on_this_bridge_yet(st):
    r = TestClient(app_module.create_app()).put(
        "/api/notify/triggers",
        json={"triggers": {"off_grid": {"target": {"type": "role", "role": "admin"}}}})
    assert r.status_code == 422 and st.alert_targets() == {}


def test_a_trigger_sends_only_to_its_target(st, fake_notifier):
    _two_devices(st)
    sends = fake_notifier(st)
    notify_engine.set_config(st, {"triggers": {"off_grid": {"target": {"type": "device", "ids": ["d2"]}}}})
    assert notify_engine.fire(st, "off_grid", gateway="Shed") == 1
    assert sends[-1]["targets"] == ["ha1::mobile_app_tab"]
    # both directions of the trigger use it
    notify_engine.fire(st, "on_grid", gateway="Shed")
    assert sends[-1]["targets"] == ["ha1::mobile_app_tab"]
    # a switched-off device in the target is left out
    st.update_notify_device("d2", enabled=False)
    assert notify_engine.fire(st, "off_grid", gateway="Shed") == 0


# ── Send test to chosen devices ──────────────────────────────────────────────────────
def test_send_test_to_chosen_devices(st, fake_notifier):
    _two_devices(st)
    sends = fake_notifier(st)
    c = TestClient(app_module.create_app())
    r = c.post("/api/notify/triggers/test", json={"device_ids": ["d1"]}).json()
    assert r == {"ok": True, "sent": 1, "total": 1}
    assert sends[-1]["targets"] == ["ha1::mobile_app_phone"]
    r = c.post("/api/notify/triggers/test", json={}).json()
    assert r["sent"] == 2 and r["total"] == 2


def test_send_test_with_no_devices_says_so(st, fake_notifier):
    sends = fake_notifier(st)
    r = TestClient(app_module.create_app()).post("/api/notify/triggers/test", json={}).json()
    assert r["ok"] is False and r["detail"] == "No devices are on" and sends == []


def test_send_test_with_the_switch_off_says_so(st, fake_notifier):
    _two_devices(st)
    fake_notifier(st, on=False)
    r = TestClient(app_module.create_app()).post("/api/notify/triggers/test", json={}).json()
    assert r["sent"] == 0 and r["detail"] == "Push notifications are off"


# ── the card ─────────────────────────────────────────────────────────────────────────
def test_send_test_opens_a_target_picker_with_an_empty_state():
    html = _html()
    assert '@click="openTestDialog()">Send test' in html
    dlg = html[html.index('data-testid="notify-test-dialog"'):html.index("<!-- Broadcast modal -->")]
    assert 'data-testid="notify-test-empty"' in dlg and "+ Add device" in dlg
    assert 'x-model="notif.testDlg.ids"' in dlg
    assert "dialog_msg('notif.testDlg?.msg')" in dlg       # the result stays in the dialog


def test_device_rows_show_on_state_and_kind_icon_and_the_dialog_sets_kind():
    html = _html()
    assert "dev.enabled ? 'On' : 'Off'" in html
    assert 'data-testid="device-kind-icon"' in html
    assert 'x-model="notif.addDev.kind" data-testid="device-kind"' in html
    assert ("Send a test notification to confirm this device receives alerts before saving"
            in html)


def test_each_trigger_has_a_target_drop_down():
    assert 'data-testid="trigger-target"' in _html()
