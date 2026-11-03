"""Go Off-Grid: the HA switch for 1723 (owner, 2026-11-03).

The same write as POST /api/offgrid, without its confirm step: in HA the switch is the
explicit action. Its state is 1723 offgridSet, what was requested; an outage islands the
house with the switch off, and Grid Status tells the two apart.
"""
from franklinwh_direct_connect_bridge.publish import entities, handle_command


class _Client:
    def __init__(self, ok=True):
        self.calls, self.ok = [], ok

    def set_offgrid(self, s, on, soc=5, host=None):
        self.calls.append((on, soc, host))
        return {"ok": self.ok, "result": 0 if self.ok else 1}


def test_the_switch_is_published_with_a_command_topic():
    cfgs, state_topic, _ = entities.discovery_configs("abc", {}, "p", "homeassistant")
    sw = dict(cfgs)["homeassistant/switch/abc/off_grid/config"]
    assert sw["name"] == "Go Off-Grid"
    assert sw["command_topic"] == "p/abc/control/off_grid/set"
    assert sw["state_topic"] == state_topic
    assert sw["value_template"] == "{{ value_json.off_grid_requested_on }}"


def test_on_goes_off_grid_and_off_reconnects_on_this_gateway():
    c = _Client()
    out = handle_command("off_grid", "ON", settings=None, client=c, host="192.0.2.10:9000")
    assert c.calls == [(True, 5, "192.0.2.10:9000")] and "accepted" in out
    handle_command("off_grid", "OFF", settings=None, client=c, host="192.0.2.10:9000")
    assert c.calls[-1] == (False, 5, "192.0.2.10:9000")


def test_a_refused_write_is_reported_not_called_accepted():
    c = _Client(ok=False)
    out = handle_command("off_grid", "ON", settings=None, client=c)
    assert c.calls == [(True, 5, None)] and "accepted" not in out and "go off-grid" in out


def test_the_state_is_what_was_requested():
    st = entities.state_payload({"power": {"off_grid": True, "offgrid_requested": 1,
                                           "off_grid_kind": "simulated"}})
    assert st["off_grid_requested_on"] is True and st["status_grid_status"] == "SimulatedOffGrid"
    st = entities.state_payload({"power": {"off_grid": True, "offgrid_requested": 0,
                                           "off_grid_kind": "outage"}})
    assert st["off_grid_requested_on"] is False and st["status_grid_status"] == "Outage"


def test_no_1723_read_means_no_switch_state():
    assert "off_grid_requested_on" not in entities.state_payload({"power": {"off_grid": False}})
    assert entities.state_payload({"power": {"off_grid": False, "offgrid_requested": 0}}
                                  )["off_grid_requested_on"] is False
