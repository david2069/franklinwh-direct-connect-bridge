"""Multi-HA instances: storage, redaction and the browse endpoints.

One bridge, many Home Assistants — the single HA_URL/HA_TOKEN pair could only
ever describe one, so a second instance had nowhere to live.
"""
import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import ha_instances
from franklinwh_direct_connect_bridge.app import create_app


def test_token_is_never_returned():
    """The API reports whether a token is set, never what it is."""
    row = {"id": "a", "name": "Main", "base_url": "http://ha:8123",
           "token": "secret-token", "is_default": 1, "enabled": 1}
    out = ha_instances.redact(row)
    assert "token" not in out
    assert out["has_token"] is True
    assert "secret-token" not in str(out)


def test_missing_token_reports_has_token_false():
    out = ha_instances.redact({"id": "a", "name": "x", "base_url": "u", "token": None,
                               "is_default": 0, "enabled": 1})
    assert out["has_token"] is False


def test_probe_never_raises_and_names_the_cause():
    """A failed probe is an answer, not an exception — the UI shows it verbatim."""
    out = ha_instances.probe("http://127.0.0.1:1", None)
    assert out["ok"] is False and "no token" in out["error"]
    out2 = ha_instances.probe("http://127.0.0.1:1", "tok")
    assert out2["ok"] is False and out2["error"]


class _Store:
    """Stand-in store with one reachable and one unreachable instance."""

    def ha_instances(self):
        return [
            {"id": "ok", "name": "Main", "base_url": "http://x", "token": "t",
             "enabled": 1, "is_default": 1},
            {"id": "down", "name": "Shed", "base_url": "http://y", "token": "t",
             "enabled": 1, "is_default": 0},
        ]


def test_one_unreachable_instance_does_not_hide_the_others(monkeypatch):
    def fake_states(base_url, token):
        if base_url == "http://y":
            raise OSError("unreachable")
        return [{"entity_id": "sensor.a", "state": "1",
                 "attributes": {"friendly_name": "A"}}]
    monkeypatch.setattr(ha_instances, "states", fake_states)
    out = ha_instances.entities(_Store())
    assert out["returned"] == 1
    assert out["entities"][0]["instance"] == "Main"
    assert "down" in out["errors"], "the failure must be reported, not swallowed"


def test_entity_filters(monkeypatch):
    monkeypatch.setattr(ha_instances, "states", lambda u, t: [
        {"entity_id": "sensor.solar", "state": "1", "attributes": {"friendly_name": "Solar"}},
        {"entity_id": "switch.pump", "state": "on", "attributes": {"friendly_name": "Pump"}},
    ])
    assert ha_instances.entities(_Store(), domain="switch")["entities"][0]["entity_id"] \
        == "switch.pump"
    assert ha_instances.entities(_Store(), search="solar")["total"] == 2   # both instances


def test_disabled_instance_is_skipped(monkeypatch):
    class S(_Store):
        def ha_instances(self):
            return [{"id": "a", "name": "n", "base_url": "u", "token": "t",
                     "enabled": 0, "is_default": 1}]
    monkeypatch.setattr(ha_instances, "states", lambda u, t: [{"entity_id": "sensor.x"}])
    assert ha_instances.entities(S())["returned"] == 0


def test_notify_targets_are_services_not_entities(monkeypatch):
    monkeypatch.setattr(ha_instances, "_get", lambda *a, **k: [
        {"domain": "light", "services": {"turn_on": {}}},
        {"domain": "notify", "services": {"mobile_app_phone": {}, "persistent": {}}},
    ])
    assert ha_instances.notify_targets("u", "t") == \
        ["notify.mobile_app_phone", "notify.persistent"]


# ── endpoints ────────────────────────────────────────────────────────────────
def test_published_lists_what_the_bridge_sends_to_ha():
    body = TestClient(create_app()).get("/api/ha/published").json()
    assert body["entities"], "the bridge publishes sensors"
    assert all(e["writable"] is False for e in body["entities"]), \
        "no control entities are published yet"


# ── notification devices ─────────────────────────────────────────────────────
def _store(tmp_path):
    from franklinwh_direct_connect_bridge.db import MetricsStore
    return MetricsStore(str(tmp_path / "t.db"))


def test_device_can_be_disabled_without_deleting(tmp_path):
    """Turning a device off for a week must not cost its configuration."""
    st = _store(tmp_path)
    st.create_notify_device(dev_id="d", alias="Phone", instance_id="i",
                            service="notify.mobile_app_x")
    st.update_notify_device("d", enabled=False)
    row = st.notify_device("d")
    assert row["enabled"] == 0
    assert row["service"] == "notify.mobile_app_x", "config survives the pause"


def test_device_crud(tmp_path):
    st = _store(tmp_path)
    st.create_notify_device(dev_id="d", alias="A", instance_id="i", service="notify.a")
    assert st.update_notify_device("d", alias="B")["alias"] == "B"
    assert st.delete_notify_device("d") is True
    assert st.notify_device("d") is None


def test_send_notification_accepts_either_service_form(monkeypatch):
    seen = {}

    class _Resp:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake_open(req, timeout=None):
        seen["url"] = req.full_url
        return _Resp()
    monkeypatch.setattr(ha_instances.urllib.request, "urlopen", fake_open)

    ha_instances.send_notification("http://ha", "t", "notify.mobile_app_x", "T", "M")
    assert seen["url"].endswith("/api/services/notify/mobile_app_x")
    ha_instances.send_notification("http://ha", "t", "mobile_app_x", "T", "M")
    assert seen["url"].endswith("/api/services/notify/mobile_app_x")


def test_send_notification_without_token_is_an_answer_not_a_raise():
    out = ha_instances.send_notification("http://ha", None, "notify.x", "T", "M")
    assert out["ok"] is False and "no token" in out["error"]


def test_device_test_needs_a_device_or_an_instance_and_service(monkeypatch):
    """Testing an UNSAVED device is the point, so instance+service is accepted —
    but one of the two forms is required."""
    import inspect
    from franklinwh_direct_connect_bridge import app as app_mod
    src = inspect.getsource(app_mod)
    assert "need device_id, or instance_id + service" in src


def test_no_template_uses_the_invented_input_class():
    """`.input` was never defined in the design system, so those fields fell back
    to the browser default — a white box on a dark page. The real class is
    `.form-control`."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1] / "src/franklinwh_direct_connect_bridge"
    css = (root / "static/css/design-system.css").read_text()
    assert ".form-control" in css and ".form-control-sm" in css
    for tpl in (root / "templates").rglob("*.html"):
        assert 'class="input' not in tpl.read_text(), f"{tpl.name} uses an undefined class"


def test_notify_picker_shows_a_friendly_name_and_the_service():
    """A raw service name is unreadable in a list of 32; HA gives no friendly name
    for a SERVICE, so one is derived. Notifications live in Settings now."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1] / "src/franklinwh_direct_connect_bridge"
    js = (root / "static/js/settings_tab.js").read_text()
    assert "friendlyService(" in js
    html = (root / "templates/tabs/settings.html").read_text()
    assert 'x-text="opt.label"' in html and 'x-text="opt.service"' in html
    assert "<datalist" not in html, "a datalist hides the friendly name"


def test_modals_do_not_dereference_a_null_object_under_x_show():
    """x-show keeps evaluating the bindings inside it, so `form.name` throws while
    `form` is null and Alpine stops updating that subtree — the fields then look
    present but do not accept typing. Use x-if, or guard every reference."""
    import pathlib, re
    root = pathlib.Path(__file__).resolve().parents[1] / "src/franklinwh_direct_connect_bridge"
    # The instances modal is still in the HA tab; the notify-device modal moved to Settings.
    ha = (root / "templates/tabs/ha.html").read_text()
    assert 'x-if="form"' in ha, "instances modal must use x-if"
    assert 'x-show="form"' not in ha, "instances modal still uses x-show"
    settings = (root / "templates/tabs/settings.html").read_text()
    assert 'x-if="notif.addDev"' in settings, "notify-device modal must use x-if"


def test_discovered_service_list_shows_friendly_names():
    """A column of raw notify.alexa_media_* strings is unreadable; the derived
    name goes above the service, same as in the picker."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1] / "src/franklinwh_direct_connect_bridge"
    html = (root / "templates/tabs/settings.html").read_text()
    assert 'x-text="opt.label"' in html and 'x-text="opt.service"' in html


def test_notify_devices_can_be_tested():
    """A device can be tested from its row (Test) and before saving (Send test in the
    add-device modal). In Settings now."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1] / "src/franklinwh_direct_connect_bridge"
    html = (root / "templates/tabs/settings.html").read_text()
    js = (root / "static/js/settings_tab.js").read_text()
    assert '@click="testDevice(dev)"' in html, "each device row has a Test button"
    assert "testNewDevice" in js, "the add-device modal can test before saving"


def test_domain_census_covers_the_whole_instance_not_the_page(monkeypatch):
    """The domain dropdown and totals must not shrink as you filter."""
    monkeypatch.setattr(ha_instances, "states", lambda u, t: [
        {"entity_id": "sensor.a", "state": "1", "attributes": {}},
        {"entity_id": "switch.b", "state": "on", "attributes": {}},
        {"entity_id": "automation.c", "state": "on", "attributes": {}},
    ])
    out = ha_instances.entities(_Store(), domain="sensor")
    assert out["returned"] == 2      # sensor.a on both instances
    assert set(out["domains"]) == {"sensor", "switch", "automation"}, \
        "dropdown reflects everything, not just the filtered domain"


def test_topic_filter_is_or_of_many_names(monkeypatch):
    monkeypatch.setattr(ha_instances, "states", lambda u, t: [
        {"entity_id": "sensor.enphase_now", "state": "1",
         "attributes": {"friendly_name": "Enphase"}},
        {"entity_id": "sensor.kitchen", "state": "1", "attributes": {}},
    ])
    out = ha_instances.entities(_Store(), topic="Solar / PV")
    assert all("enphase" in e["entity_id"] for e in out["entities"])
    assert "Solar / PV" in ha_instances.TOPICS


def test_exposed_only_filter(monkeypatch, tmp_path):
    monkeypatch.setattr(ha_instances, "states", lambda u, t: [
        {"entity_id": "sensor.a", "state": "1", "attributes": {}},
        {"entity_id": "sensor.b", "state": "1", "attributes": {}},
    ])
    ex = {"ok:sensor.a"}      # only a is exposed, on the "ok" instance
    out = ha_instances.entities(_Store(), exposed=True, exposed_ids=ex)
    ids = {e["entity_id"] for e in out["entities"]}
    assert ids == {"sensor.a"}
    assert out["exposed_count"] == 1


def test_call_service_builds_url_and_guards_token(monkeypatch):
    from franklinwh_direct_connect_bridge import ha_instances
    # No token → refused, no HTTP.
    r = ha_instances.call_service("http://ha:8123", None, "switch", "turn_on", {"entity_id": "switch.x"})
    assert r["ok"] is False and "no token" in r["error"]
    # Missing domain/service → refused.
    assert ha_instances.call_service("http://ha", "T", "", "turn_on")["ok"] is False
    # With a token, the correct URL + payload are POSTed.
    seen = {}
    class _Resp:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *a): return False
    def _urlopen(req, timeout=None):
        seen["url"] = req.full_url; seen["data"] = req.data; seen["auth"] = req.headers.get("Authorization")
        return _Resp()
    monkeypatch.setattr(ha_instances.urllib.request, "urlopen", _urlopen)
    r = ha_instances.call_service("http://ha:8123/", "TOK", "climate", "set_temperature",
                                  {"entity_id": "climate.lounge", "temperature": 21})
    assert r["ok"] is True
    assert seen["url"] == "http://ha:8123/api/services/climate/set_temperature"
    assert seen["auth"] == "Bearer TOK"
    import json
    assert json.loads(seen["data"]) == {"entity_id": "climate.lounge", "temperature": 21}
