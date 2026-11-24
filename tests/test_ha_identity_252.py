"""#252 / #92: the gateway devices move to the fwh_dc ids, keeping what the user has.

Measured on HA 2026.10.1 (#252 spike): publishing the new configs first, on the same device
(both identifiers), then removing the old configs and renaming each new entity into the old
entity_id keeps the device_id, the entity_id and its history. The user's own name, icon,
area and so on live on the old registry row, so they are copied across.
"""
import json
import socket
import threading

import pytest

from franklinwh_direct_connect_bridge.db import MetricsStore
from franklinwh_direct_connect_bridge.publish import entities, identity, mqtt_scan


class S:
    mqtt_prefix = ""
    ha_discovery_prefix = "homeassistant"
    mqtt_host, mqtt_port, mqtt_username, mqtt_password = "b", 1883, "", ""


@pytest.fixture
def undecided():
    identity.set_mode(None)
    yield
    identity.set_mode(identity.CURRENT)


@pytest.fixture
def st(tmp_path):
    return MetricsStore(str(tmp_path / "m.db"))


def _never(*a, **k):
    raise AssertionError("not expected")


# ── the ids ────────────────────────────────────────────────────────────────────────────
def test_new_ids_topics_and_prefix():
    cfgs, state_t, avail_t = entities.discovery_configs(
        "n1", entities.device_info("n1", "SN1"), identity.prefix(S), "homeassistant")
    assert all(c["unique_id"].startswith("fwh_dc_n1_") for _, c in cfgs)
    assert all(t.split("/")[2] == "fwh_dc_n1" for t, _ in cfgs)
    assert all(c["device"]["identifiers"] == ["fwh_dc_n1"] for _, c in cfgs)
    assert state_t == "fwh_dc/n1/state" and avail_t == "fwh_dc/n1/availability"
    # entity ids are not part of the move: object_id is unchanged
    assert all(c["object_id"].startswith("franklinwh_n1_") for _, c in cfgs)


def test_while_moving_the_device_carries_both_identifiers():
    d = entities.device_info("n1", "SN1", moving=True)
    assert d["identifiers"] == ["fwh_dc_n1", "franklinwh_n1"]


def test_legacy_mode_keeps_every_old_id():
    identity.set_mode("legacy")
    cfgs, state_t, _ = entities.discovery_configs(
        "n1", entities.device_info("n1", "SN1", moving=True), identity.prefix(S), "homeassistant")
    assert all(c["unique_id"].startswith("franklinwh_n1_") for _, c in cfgs)
    assert all(t.split("/")[2] == "n1" for t, _ in cfgs)
    assert cfgs[0][1]["device"]["identifiers"] == ["franklinwh_n1"]
    assert state_t == "franklinwh-local/n1/state"


def test_the_users_own_prefix_is_kept():
    class Own(S):
        mqtt_prefix = "mine"
    assert identity.prefix(Own) == "mine"
    identity.set_mode("legacy")
    assert identity.prefix(Own) == "mine"


def test_node_of_reads_both_spellings():
    assert identity.node_of("fwh_dc_abc") == "abc"
    assert identity.node_of("franklinwh_abc") == "abc"
    assert identity.node_of("franklinwh_modbus_x") == "modbus_x"   # caller checks ownership
    assert identity.node_of("other_abc") == ""


# ── the decision ───────────────────────────────────────────────────────────────────────
def test_a_fresh_install_starts_on_fwh_dc(undecided, st):
    assert identity.decide(S, st, nodes=lambda s: set(), session=_never, live=_never) == "fwh_dc"
    assert identity.load(st)["mode"] == "fwh_dc"


def test_once_moved_the_broker_is_not_read_again(undecided, st):
    st.set_config(identity.KEY, json.dumps({"mode": "fwh_dc"}))
    assert identity.decide(S, st, nodes=_never) == "fwh_dc"


def test_without_home_assistant_the_old_ids_stay_and_it_says_why(undecided, st):
    assert identity.decide(S, st, nodes=lambda s: {"n1"}, session=None, live=_never) == "legacy"
    assert identity.load(st)["reason"] == identity.NO_HA
    assert identity.prefix(S) == "franklinwh-local"
    identity.set_mode(None)                                      # next start: tried again
    calls = []
    identity.decide(S, st, nodes=lambda s: calls.append(1) or {"n1"}, session=None)
    assert calls


def test_an_older_bridge_still_publishing_blocks_the_move(undecided, st, monkeypatch):
    monkeypatch.setattr(identity, "_ha_ok", lambda s: True)
    assert identity.decide(S, st, nodes=lambda s: {"n1"}, session=object(),
                           live=lambda s: True) == "legacy"
    assert identity.load(st)["reason"] == identity.OLD_LIVE


def test_with_home_assistant_it_moves(undecided, st, monkeypatch):
    monkeypatch.setattr(identity, "_ha_ok", lambda s: True)
    cleared = []
    assert identity.decide(S, st, nodes=lambda s: {"n1", "n2"}, session=object(),
                           live=lambda s: False, clear=cleared.append) == "fwh_dc"
    assert identity.load(st)["from"] == ["n1", "n2"] and cleared == [S]


def test_an_unreadable_broker_keeps_the_old_ids_and_records_nothing(undecided, st):
    def boom(s):
        raise ConnectionError("down")
    assert identity.decide(S, st, nodes=boom) == "legacy"
    assert identity.load(st) == {}


def test_a_non_admin_token_is_no_way_in():
    class Ws:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def call(self, p): return {"is_admin": False}
    assert identity._ha_ok(lambda: Ws()) is False


# ── what is ours on the broker ─────────────────────────────────────────────────────────
def _cfg(ident, sw="Direct Connect Bridge v1"):
    return json.dumps({"device": {"identifiers": [ident], "sw_version": sw}}).encode()


def test_legacy_nodes_are_ours_with_the_old_identifier_only():
    msgs = {"a": _cfg("franklinwh_n1"), "b": _cfg("franklinwh_n1"),
            "c": _cfg("fwh_dc_n2"),                                  # already moved
            "d": _cfg("franklinwh_n3", sw="Modbus Bridge v2"),      # not ours
            "e": _cfg("franklinwh_fwh_dc_bridge"),                  # the bridge device
            "f": b"not json"}
    got = identity.legacy_nodes(S, collect=lambda *a, **k: (msgs, None))
    assert got == {"n1"}


def test_scan_reads_the_node_from_the_new_identifier():
    msgs = {"homeassistant/sensor/fwh_dc_n1/soc/config": _cfg("fwh_dc_n1")}
    out = mqtt_scan.find_orphans(msgs, ["n1"], "homeassistant")
    assert out["counts"]["orphaned"] == 0 and out["live"][0]["node"] == "n1"


def test_pending_reads_only_a_node_that_has_to_move(st):
    seen = []
    def retained(s, topics):
        seen.append(topics)
        return {topics[0]: b"x"}
    assert identity.pending("n1", S, st, retained=retained) == (False, {})  # fresh install
    st.set_config(identity.KEY, json.dumps({"mode": "fwh_dc", "from": ["n1"]}))
    move, got = identity.pending("n1", S, st, retained=retained)
    assert move and got and all(t.startswith("homeassistant/") and "/n1/" in t for t in seen[0])
    st.set_config(identity.KEY, json.dumps({"mode": "fwh_dc", "from": ["n1"],
                                            "nodes": {"n1": {"problems": ["x"]}}}))
    assert identity.pending("n1", S, st, retained=lambda s, t: {})[0]       # finish it
    st.set_config(identity.KEY, json.dumps({"mode": "fwh_dc", "from": ["n1"],
                                            "nodes": {"n1": {"problems": []}}}))
    assert identity.pending("n1", S, st, retained=retained) == (False, {})  # moved


# ── one gateway's move ─────────────────────────────────────────────────────────────────
class FakeHA:
    """The entity registry over the websocket: old rows, and the new ones HA added when
    the new configs were published (with HA's _2 ids)."""

    def __init__(self, add_new=True):
        self.rows = [
            {"platform": "mqtt", "unique_id": "franklinwh_n1_soc", "entity_id": "sensor.my_soc",
             "name": "My SoC", "icon": "mdi:car-battery", "area_id": "garage", "labels": [],
             "hidden_by": "user", "disabled_by": None,
             "options": {"sensor": {"display_precision": 2}, "mqtt": {"x": 1}}},
            {"platform": "mqtt", "unique_id": "franklinwh_n1_grid_w",
             "entity_id": "sensor.franklinwh_direct_n1_grid_power", "name": None, "icon": None,
             "area_id": None, "labels": [], "hidden_by": None, "disabled_by": "integration",
             "options": {}},
            {"platform": "other", "unique_id": "franklinwh_n1_soc", "entity_id": "sensor.x"},
        ]
        if add_new:
            self.rows += [
                {"platform": "mqtt", "unique_id": "fwh_dc_n1_soc",
                 "entity_id": "sensor.franklinwh_direct_n1_state_of_charge_2", "options": {}},
                {"platform": "mqtt", "unique_id": "fwh_dc_n1_grid_w",
                 "entity_id": "sensor.franklinwh_direct_n1_grid_power_2", "options": {}}]
        self.updates = []
        self.removed = False

    def __call__(self):
        return self

    def __enter__(self): return self
    def __exit__(self, *a): pass

    def call(self, p):
        if p["type"] == "config/entity_registry/list":
            rows = self.rows
            if self.removed:
                rows = [r for r in rows if not (r["platform"] == "mqtt"
                                                and r["unique_id"].startswith("franklinwh_"))]
            return rows
        if p["type"] == "config/entity_registry/get_entries":
            by = {r["entity_id"]: dict(r, aliases=["battery"] if r["entity_id"] == "sensor.my_soc"
                                       else []) for r in self.rows}
            return {e: by.get(e) for e in p["entity_ids"]}
        if p["type"] == "config/entity_registry/update":
            self.updates.append(p)
            return {}
        raise AssertionError(p)


def _move(ha, removed_left=(), **k):
    calls = []
    def remove(topics):
        calls.append(topics)
        ha.removed = True
        return list(removed_left)
    old = {"homeassistant/sensor/n1/soc/config": b"{}",
           "homeassistant/sensor/n1/grid_w/config": b"{}"}
    res = identity.move_node(S, None, "n1", {"soc", "grid_w", "load_w"}, old, ha,
                             remove=remove, wait_s=0.0, sleep=lambda s: None, **k)
    return res, calls


def test_the_move_renames_into_the_old_ids_and_keeps_the_users_settings():
    ha = FakeHA()
    res, removed = _move(ha)
    assert res["problems"] == [] and res["moved"] == 2 and res["renamed"] == 2
    soc = [u for u in ha.updates if u["entity_id"].endswith("state_of_charge_2")][0]
    assert soc["new_entity_id"] == "sensor.my_soc"
    assert (soc["name"], soc["icon"], soc["area_id"], soc["aliases"], soc["hidden_by"]) == \
        ("My SoC", "mdi:car-battery", "garage", ["battery"], "user")
    opts = [u for u in ha.updates if "options_domain" in u]
    assert [(u["entity_id"], u["options_domain"]) for u in opts] == [("sensor.my_soc", "sensor")]
    grid = [u for u in ha.updates if u["entity_id"].endswith("grid_power_2")][0]
    assert grid["new_entity_id"] == "sensor.franklinwh_direct_n1_grid_power"
    assert "disabled_by" not in grid and "name" not in grid       # nothing the user set
    # the old configs went first, then the old state topics under the old prefix
    assert removed[0] == sorted(["homeassistant/sensor/n1/soc/config",
                                 "homeassistant/sensor/n1/grid_w/config"])
    assert removed[1] and all(t.startswith("franklinwh-local/n1/") for t in removed[1])


def test_nothing_is_removed_until_home_assistant_has_the_new_entities():
    ha = FakeHA(add_new=False)
    res, removed = _move(ha)
    assert removed == [] and ha.updates == []
    assert "didn't add 2 new entities" in res["problems"][0]


def test_old_topics_still_retained_stop_the_renames():
    ha = FakeHA()
    res, _ = _move(ha, removed_left=["homeassistant/sensor/n1/soc/config"])
    assert ha.updates == [] and "still retained" in res["problems"][0]


def test_the_move_is_recorded_per_gateway(st):
    identity.record(st, "n1", {"moved": 2, "renamed": 2, "kept": 1, "problems": []})
    assert identity.view(st)["nodes"]["n1"]["moved"] == 2


# ── the websocket client ───────────────────────────────────────────────────────────────
def _serve(responses):
    """A one-connection websocket server: handshake, auth, then one reply per command."""
    import base64
    import hashlib
    from franklinwh_direct_connect_bridge import ha_supervisor as hs
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    got = []

    def frame(obj):
        data = json.dumps(obj).encode()
        n = len(data)
        head = bytes([0x81]) + (bytes([n]) if n < 126 else bytes([126]) + n.to_bytes(2, "big"))
        return head + data

    def run():
        c, _ = srv.accept()
        req = b""
        while b"\r\n\r\n" not in req:
            req += c.recv(4096)
        got.append(req.split(b"\r\n", 1)[0].decode())
        key = [ln.split(b": ", 1)[1] for ln in req.split(b"\r\n") if ln.startswith(b"Sec-WebSocket-Key")][0]
        acc = base64.b64encode(hashlib.sha1(key + b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11").digest())
        c.sendall(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
                  b"Connection: Upgrade\r\nSec-WebSocket-Accept: " + acc + b"\r\n\r\n")
        c.sendall(frame({"type": "auth_required"}))
        rd = hs._WsReader(c)
        got.append(rd.message())
        c.sendall(frame({"type": "auth_ok"}))
        for r in responses:
            m = rd.message()
            got.append(m)
            c.sendall(frame({"id": m["id"], "type": "result", "success": True, "result": r}))
        c.close()
    threading.Thread(target=run, daemon=True).start()
    return srv.getsockname()[1], got


def test_ws_session_to_an_instance_url_sends_several_commands():
    from franklinwh_direct_connect_bridge import ha_supervisor as hs
    port, got = _serve([{"is_admin": True}, [1, 2]])
    with hs.WsSession(url=f"http://127.0.0.1:{port}", token="t0k") as ws:
        assert ws.call({"type": "auth/current_user"}) == {"is_admin": True}
        assert ws.call({"type": "config/entity_registry/list"}) == [1, 2]
    assert got[0] == "GET /api/websocket HTTP/1.1"
    assert got[1] == {"type": "auth", "access_token": "t0k"}
    assert [m["id"] for m in got[2:]] == [1, 2]


def test_the_mqtt_tab_shows_the_ids_and_the_move(st, monkeypatch):
    from fastapi.testclient import TestClient
    from franklinwh_direct_connect_bridge import app as app_module, db, state
    monkeypatch.setattr(db, "get_store", lambda s: st)
    identity.record(st, "n1", {"at": 1, "moved": 3, "renamed": 1, "kept": 1, "problems": []})
    c = TestClient(app_module.create_app())
    g = state.register_gateway("gw-id", "10.0.0.1", "House")
    g.node = "n1"
    try:
        d = c.get("/api/mqtt/config?gateway=gw-id").json()
    finally:
        state.unregister_gateway("gw-id")
    assert d["prefix"] == "fwh_dc"
    assert d["identity"]["mode"] == "fwh_dc" and d["identity"]["move"]["moved"] == 3
    html = (__import__("pathlib").Path(app_module.__file__).parent / "templates/tabs/mqtt.html").read_text()
    assert 'data-testid="mqtt-identity"' in html


def test_an_old_entity_home_assistant_kept_is_removed_and_the_new_one_takes_its_id():
    """Measured on the VM (G1): an entity the user disabled keeps its registry row when its
    config goes, so the move removes it, renames the new one and disables it again."""
    class Sticky(FakeHA):
        def call(self, p):
            if p["type"] == "config/entity_registry/remove":
                self.rows = [r for r in self.rows if r["entity_id"] != p["entity_id"]]
                return None
            if p["type"] == "config/entity_registry/list" and self.removed:
                return [r for r in self.rows if not (r["platform"] == "mqtt"
                        and r["unique_id"] == "franklinwh_n1_soc")]       # grid_w stays
            return super().call(p)
    ha = Sticky()
    res, _ = _move(ha)
    assert res["problems"] == [] and res["moved"] == 2
    grid = [u for u in ha.updates if u["entity_id"].endswith("grid_power_2")][0]
    assert grid["new_entity_id"] == "sensor.franklinwh_direct_n1_grid_power"


def test_kept_counts_only_what_the_user_set():
    ha = FakeHA()
    res, _ = _move(ha)
    assert res["kept"] == 1                       # soc; grid_w has HA's defaults only


def test_automations_that_name_a_moved_row_are_named():
    """G1: a device condition names the entity by its registry row; that row is new after
    the move, so Home Assistant turns the automation off on the next reload."""
    class WithAutos(FakeHA):
        def __init__(self):
            super().__init__()
            self.rows[0]["id"] = "row-soc"
            self.rows += [{"platform": "automation", "entity_id": "automation.by_device"},
                          {"platform": "automation", "entity_id": "automation.by_id"}]

        def call(self, p):
            if p["type"] == "automation/config":
                c = {"automation.by_device": {"conditions": [{"entity_id": "row-soc"}]},
                     "automation.by_id": {"triggers": [{"entity_id": "sensor.my_soc"}]}}
                return {"config": c[p["entity_id"]]}
            return super().call(p)
    res, _ = _move(WithAutos())
    assert res["refs"] == ["automation.by_device"] and res["problems"] == []
    assert "automation.by_device" in res["notes"][0]


def test_a_finished_retry_adds_to_the_first_run(st):
    identity.record(st, "n1", {"moved": 62, "renamed": 62, "kept": 5, "problems": ["x"]})
    identity.record(st, "n1", {"moved": 1, "renamed": 1, "kept": 1, "problems": []})
    n = identity.view(st)["nodes"]["n1"]
    assert (n["moved"], n["kept"], n["problems"]) == (63, 6, [])
