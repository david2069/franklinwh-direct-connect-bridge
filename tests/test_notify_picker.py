"""Choosing a notification target: the instance first, then a target you can tell apart.

Owner, 2026-10-15: "We need Notification devices filter or have setup specifically for that
where u choose the HA Instance like Energipay does", with a screenshot of eight notify
targets where `notify.pixel_tablet` and `notify.pixel_tablet_2` differ only by a timestamp.

Also: "should be able to disable without deleting" and "must use friendly names".
"""
import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import (app as app_module, config, db, environment,
                                              ha_instances)
from franklinwh_direct_connect_bridge.db import MetricsStore

STATES = [
    {"entity_id": "notify.pixel_tablet", "state": "unknown",
     "attributes": {"friendly_name": "Pixel Tablet"}, "last_updated": None},
    {"entity_id": "notify.pixel_tablet_2", "state": "2026-10-15T08:22:22+00:00",
     "attributes": {"friendly_name": "Pixel Tablet"},
     "last_updated": "2026-10-15T08:22:22+00:00"},
]


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    st = MetricsStore(str(tmp_path / "m.db"))
    monkeypatch.setattr(environment, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "_settings", None)
    monkeypatch.setattr(db, "get_store", lambda s: st)
    st.create_ha_instance(ha_id="a", name="Home", base_url="http://192.0.2.5:8123",
                          token="t1", is_default=True)
    st.create_ha_instance(ha_id="b", name="Shed", base_url="http://192.0.2.6:8123",
                          token="t2")
    monkeypatch.setattr(ha_instances, "notify_targets",
                        lambda url, tok: (["notify.pixel_tablet", "notify.pixel_tablet_2"]
                                          if "192.0.2.5" in url else ["notify.shed_phone"]))
    monkeypatch.setattr(ha_instances, "states",
                        lambda url, tok: STATES if "192.0.2.5" in url else [])
    return st


def test_targets_can_be_scoped_to_one_instance(ctx):
    """One bridge, several Home Assistants — a notification goes to exactly one of them."""
    c = TestClient(app_module.create_app())
    all_t = c.get("/api/ha/notify-targets").json()["targets"]
    assert {t["instance_id"] for t in all_t} == {"a", "b"}
    one = c.get("/api/ha/notify-targets?instance=a").json()["targets"]
    assert {t["instance_id"] for t in one} == {"a"}


def test_a_duplicate_target_is_named_as_shadowing_the_original(ctx):
    c = TestClient(app_module.create_app())
    by_service = {t["service"]: t for t in
                  c.get("/api/ha/notify-targets?instance=a").json()["targets"]}
    assert by_service["notify.pixel_tablet_2"]["duplicate_of"] == "notify.pixel_tablet"
    assert by_service["notify.pixel_tablet"]["duplicate_of"] is None


def test_last_seen_is_carried_so_the_live_one_can_be_identified(ctx):
    """The ONLY evidence Home Assistant gives about which duplicate is live."""
    c = TestClient(app_module.create_app())
    by_service = {t["service"]: t for t in
                  c.get("/api/ha/notify-targets?instance=a").json()["targets"]}
    assert by_service["notify.pixel_tablet_2"]["last_updated"]
    assert by_service["notify.pixel_tablet"]["last_updated"] is None


def test_friendly_names_come_from_home_assistant(ctx):
    c = TestClient(app_module.create_app())
    t = c.get("/api/ha/notify-targets?instance=a").json()["targets"][0]
    assert t["name"] == "Pixel Tablet"


def test_a_target_with_no_entity_is_still_offered(ctx):
    """Notify targets are SERVICES; not all of them have a matching entity."""
    c = TestClient(app_module.create_app())
    t = c.get("/api/ha/notify-targets?instance=b").json()["targets"]
    assert [x["service"] for x in t] == ["notify.shed_phone"]
    assert t[0]["name"] == "" and t[0]["last_updated"] is None


def test_an_unreadable_instance_does_not_hide_the_others(ctx, monkeypatch):
    def _targets(url, tok):
        if "192.0.2.6" in url:
            raise OSError("unreachable")
        return ["notify.pixel_tablet"]
    monkeypatch.setattr(ha_instances, "notify_targets", _targets)
    body = TestClient(app_module.create_app()).get("/api/ha/notify-targets").json()
    assert [t["service"] for t in body["targets"]] == ["notify.pixel_tablet"]
    assert "b" in body["errors"]


# -- disable without deleting ------------------------------------------------------------
def test_a_device_reports_its_instance_being_disabled(ctx):
    ctx.create_notify_device(dev_id="d1", alias="Tablet", instance_id="a",
                             service="notify.pixel_tablet")
    ctx.update_ha_instance("a", enabled=False)
    c = TestClient(app_module.create_app())
    dev = c.get("/api/ha/notify-devices").json()["devices"][0]
    # The device is still ON; what changed is the instance carrying it.
    assert dev["enabled"] is True and dev["instance_disabled"] is True


def test_a_disabled_instance_offers_no_targets(ctx):
    ctx.update_ha_instance("a", enabled=False)
    body = TestClient(app_module.create_app()).get("/api/ha/notify-targets").json()
    assert {t["instance_id"] for t in body["targets"]} == {"b"}


def test_a_disabled_instance_suppresses_delivery_without_failing(ctx, monkeypatch):
    """Suppressed, not failed: nothing went wrong, it was switched off."""
    from franklinwh_direct_connect_bridge import notify_engine
    ctx.create_notify_device(dev_id="d1", alias="Tablet", instance_id="a",
                             service="notify.pixel_tablet")
    ctx.update_ha_instance("a", enabled=False)
    sent = []
    monkeypatch.setattr(ha_instances, "send_notification",
                        lambda *a, **k: sent.append(a) or {"ok": True})
    notify_engine.fire(ctx, "test", "T", "M")
    assert sent == []
    log = ctx.notify_log(limit=5)
    assert any("instance disabled" in (e.get("device") or "") for e in log)


# -- the Guide, when the docs site is not bundled -----------------------------------------
# Live add-on, 2026-10-15: the Guide tab rendered {"detail":"Not Found"} as the page. The
# mkdocs site is built from the sibling library checkout into docs_site/, which is
# GITIGNORED — so the add-on, built from the repository, has no site to serve.

def test_the_guide_reports_whether_it_is_bundled(ctx, monkeypatch):
    import franklinwh_direct_connect_bridge.app as m
    monkeypatch.setenv("FWH_DOCS_DIR", "/nonexistent-docs-dir")
    body = TestClient(m.create_app()).get("/api/guide").json()
    assert body["bundled"] is False
    assert body["published_url"].startswith("https://")
    assert body["url"] == body["published_url"]       # send people somewhere that works
    assert body["reason"]


def test_a_bundled_guide_is_served_locally(ctx, monkeypatch, tmp_path):
    import franklinwh_direct_connect_bridge.app as m
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text("<html><body>docs</body></html>")
    monkeypatch.setenv("FWH_DOCS_DIR", str(site))
    body = TestClient(m.create_app()).get("/api/guide").json()
    assert body["bundled"] is True and body["url"] == "guide/"
