"""#785, path B (owner 2026-11-20): the wizard's Home Assistant step on an add-on with no
MQTT broker says "install Mosquitto" first, with a button to its page; the checks read as
ordered steps; the step re-checks every 5 s; after Yes the bridge confirms Home Assistant's
discovered MQTT integration (handler mqtt, source hassio, only while HA has none); a
Supervisor "Service not enabled" at boot is "No MQTT broker yet" at INFO."""
import io
import json
import logging
import pathlib
import urllib.error

import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import (app as app_module, config, db, environment,
                                              ha_instances, ha_supervisor, state)
from franklinwh_direct_connect_bridge.db import MetricsStore

PKG = pathlib.Path(__file__).resolve().parents[1] / "src" / "franklinwh_direct_connect_bridge"
NO_BROKER = {"found": False, "no_broker": True,
             "error": "No MQTT service registered — install the Mosquitto add-on"}


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    st = MetricsStore(str(tmp_path / "m.db"))
    monkeypatch.setattr(environment, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "_settings", None)
    monkeypatch.setattr(db, "get_store", lambda s: st)
    monkeypatch.setattr(environment, "IS_HA_ADDON", True)
    monkeypatch.setattr(app_module, "discover_mqtt", lambda: dict(NO_BROKER))
    state.reset_gateways()
    yield st
    state.reset_gateways()


def _client(monkeypatch, mqtt_enabled):
    monkeypatch.setenv("MQTT_ENABLED", "true" if mqtt_enabled else "false")
    config._settings = None
    return TestClient(app_module.create_app())


def _checks(c):
    return {x["id"]: x for x in c.get("/api/setup/ha-checks").json()["checks"]}


def _publisher():
    gw = state.register_gateway("g1", "192.0.2.10", "aGate")
    gw.publish_ha = True
    gw.mqtt_connected = False
    return gw


# ── 1. the broker remedy ────────────────────────────────────────────────────────────────
def test_addon_without_a_broker_says_install_mosquitto_first(ctx, monkeypatch):
    _publisher()
    b = _checks(_client(monkeypatch, True))["mqtt_broker"]
    assert b["ok"] is False
    assert b["remedy"] == ("Install the Mosquitto broker app. The Bridge connects on its own "
                           "once it is running.")
    assert b["install_url"] == ha_supervisor.MOSQUITTO_URL


def test_addon_without_a_broker_and_publishing_off_also_says_install(ctx, monkeypatch):
    b = _checks(_client(monkeypatch, False))["mqtt_broker"]
    assert b["remedy"].startswith("Install the Mosquitto broker app.")
    assert b["install_url"]


def test_addon_with_a_broker_has_no_install_button(ctx, monkeypatch):
    monkeypatch.setattr(app_module, "discover_mqtt", lambda: {"found": True, "host": "core-mosquitto"})
    b = _checks(_client(monkeypatch, False))["mqtt_broker"]
    assert "turn publishing on" in b["remedy"] and not b.get("install_url")


def test_standalone_points_to_the_mqtt_tab_and_running_a_broker(ctx, monkeypatch):
    monkeypatch.setattr(environment, "IS_HA_ADDON", False)
    monkeypatch.setattr(app_module, "discover_mqtt",
                        lambda: {"found": False, "error": "not running as an HA add-on", "source": "dev"})
    _publisher()
    b = _checks(_client(monkeypatch, True))["mqtt_broker"]
    assert not b.get("install_url")
    assert "MQTT tab" in b["remedy"] and "broker" in b["remedy"]


# ── 2. ordered steps ────────────────────────────────────────────────────────────────────
def test_checks_after_the_first_failing_one_wait_for_it(ctx, monkeypatch):
    _publisher()
    c = _checks(_client(monkeypatch, True))
    assert c["mqtt_broker"]["ok"] is False and not c["mqtt_broker"].get("waiting")
    for k in ("ha_linked", "ha_mqtt", "entities"):
        assert c[k]["waiting"] is True, k                       # shown as waiting, own result kept


def test_nothing_waits_once_the_earlier_steps_pass(ctx, monkeypatch):
    ctx.create_ha_instance(ha_id="self", name="HA", base_url="http://supervisor/core",
                           token="t", is_default=True)
    gw = _publisher()
    gw.mqtt_connected = True
    monkeypatch.setattr(app_module, "discover_mqtt", lambda: {"found": True})
    monkeypatch.setattr(ha_instances, "probe", lambda u, t: {"ok": True})
    monkeypatch.setattr(ha_instances, "components", lambda u, t: ["sensor"])
    c = _checks(_client(monkeypatch, True))
    assert c["ha_mqtt"]["ok"] is False and not c["ha_mqtt"].get("waiting")
    assert "Discovered → MQTT → Add" in c["ha_mqtt"]["remedy"]
    assert c["entities"]["waiting"] is True


# ── 6. the boot log ─────────────────────────────────────────────────────────────────────
def test_service_not_enabled_is_no_broker_yet_at_info(monkeypatch, caplog):
    monkeypatch.setattr(ha_supervisor, "IS_HA_ADDON", True)
    monkeypatch.setenv("SUPERVISOR_TOKEN", "t")
    def refused(*a, **k):
        raise urllib.error.HTTPError("http://supervisor/services/mqtt", 400, "Bad Request", {},
                                     io.BytesIO(b'{"result":"error","message":"Service not enabled"}'))
    monkeypatch.setattr(ha_supervisor.urllib.request, "urlopen", refused)
    with caplog.at_level(logging.INFO, logger="franklinwh_direct_connect_bridge.ha_supervisor"):
        r = ha_supervisor.discover_mqtt()
    assert r["found"] is False and r["no_broker"] is True
    recs = [x for x in caplog.records if "MQTT" in x.getMessage()]
    assert recs and all(x.levelno == logging.INFO for x in recs)
    assert any("No MQTT broker yet" in x.getMessage() for x in recs)


def test_other_supervisor_failures_still_warn(monkeypatch, caplog):
    monkeypatch.setattr(ha_supervisor, "IS_HA_ADDON", True)
    monkeypatch.setenv("SUPERVISOR_TOKEN", "t")
    def boom(*a, **k):
        raise urllib.error.HTTPError("u", 401, "Unauthorized", {}, io.BytesIO(b"401"))
    monkeypatch.setattr(ha_supervisor.urllib.request, "urlopen", boom)
    with caplog.at_level(logging.INFO, logger="franklinwh_direct_connect_bridge.ha_supervisor"):
        r = ha_supervisor.discover_mqtt()
    assert r["found"] is False and not r.get("no_broker")
    assert any(x.levelno == logging.WARNING for x in caplog.records)


# ── 4. confirming the discovered MQTT integration ───────────────────────────────────────
FLOWS = [{"flow_id": "a", "handler": "zwave_js", "context": {"source": "hassio"}},
         {"flow_id": "b", "handler": "mqtt", "context": {"source": "user"}},
         {"flow_id": "c", "handler": "mqtt", "context": {"source": "hassio"}}]


@pytest.fixture
def confirm(ctx, monkeypatch):
    ctx.create_ha_instance(ha_id="self", name="HA", base_url="http://supervisor/core",
                           token="t", is_default=True)
    monkeypatch.setattr(ha_instances, "components", lambda u, t: ["sensor"])
    sent = []
    monkeypatch.setattr(ha_supervisor, "ws_call", lambda payload, **k: list(FLOWS))
    def post(flow_id):
        sent.append(flow_id)
        return {"type": "create_entry", "title": "Mosquitto broker"}
    monkeypatch.setattr(ha_supervisor, "confirm_flow", post)
    return sent


def test_only_the_hassio_mqtt_flow_is_confirmed_and_audited(confirm, ctx, monkeypatch):
    r = _client(monkeypatch, True).post("/api/setup/ha-mqtt/confirm")
    assert r.status_code == 200 and r.json()["ok"] is True
    assert confirm == ["c"]
    assert r.json()["message"] == "Added Home Assistant's MQTT integration for the Mosquitto broker."
    assert any(e["action"] == "ha_mqtt_confirm" for e in ctx.control_log(limit=10))


def test_an_existing_mqtt_entry_is_left_alone(confirm, ctx, monkeypatch):
    monkeypatch.setattr(ha_instances, "components", lambda u, t: ["mqtt"])
    r = _client(monkeypatch, True).post("/api/setup/ha-mqtt/confirm").json()
    assert r["ok"] is True and r["already"] is True and confirm == []


def test_only_after_yes_and_only_on_the_addon(confirm, ctx, monkeypatch):
    assert _client(monkeypatch, False).post("/api/setup/ha-mqtt/confirm").status_code == 409
    monkeypatch.setattr(environment, "IS_HA_ADDON", False)
    assert _client(monkeypatch, True).post("/api/setup/ha-mqtt/confirm").status_code == 409
    assert confirm == []


@pytest.mark.parametrize("fail", ["ws", "gone", "401", "timeout", "none"])
def test_failures_fall_back_to_the_remedy(confirm, ctx, monkeypatch, fail):
    if fail == "ws":
        monkeypatch.setattr(ha_supervisor, "ws_call",
                            lambda p, **k: (_ for _ in ()).throw(ConnectionError("refused")))
    elif fail == "none":
        monkeypatch.setattr(ha_supervisor, "ws_call", lambda p, **k: FLOWS[:2])
    else:
        err = {"gone": urllib.error.HTTPError("u", 404, "Not Found", {}, io.BytesIO(b"")),
               "401": urllib.error.HTTPError("u", 401, "Unauthorized", {}, io.BytesIO(b"")),
               "timeout": TimeoutError("timed out")}[fail]
        def raise_(fid):
            raise err
        monkeypatch.setattr(ha_supervisor, "confirm_flow", raise_)
    r = _client(monkeypatch, True).post("/api/setup/ha-mqtt/confirm")
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] is False and "Settings → Devices & services → Discovered → MQTT → Add" in j["remedy"]


# ── 3. the step re-checks every 5 s and stops ───────────────────────────────────────────
def test_the_step_polls_every_5_s_and_stops_when_done_or_left():
    js = (PKG / "static" / "js" / "setup_wizard.js").read_text()
    body = js[js.index("watchHa() {"):][:1500]
    assert "5000" in body and "clearInterval" in body
    assert "this.step !== 'publish'" in body                      # left the step
    assert "every(c => c.ok === true)" in body                    # all pass
    assert "api/setup/ha-mqtt/confirm" in js and "ha.saidYes" in js
    html = (PKG / "templates" / "partials" / "setup_wizard.html").read_text()
    assert "c.install_url" in html and "Install Mosquitto" in html and "c.waiting" in html
