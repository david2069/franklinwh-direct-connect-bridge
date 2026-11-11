"""Smart circuits in the System view carry the names saved on the aGate (owner, 2026-11-12:
the Smart Circuits tab said "Test Switch", the System view "Circuit 2"). The names come
from the same 1409 read as the on/off state; Customise diagram still wins over them."""
from franklinwh_direct_connect_bridge import client, config, mockgw, state, system_view
import franklinwh_system_view as sv


def _summ(**names):
    return {"ok": True, "power": {"soc": 50.0}, "battery": {"soc": 50.0, "count": 1},
            "circuits_on": {1: True, 2: False, 3: False}, "circuit_names": names}


def test_the_poll_reads_the_names_with_the_state():
    host = mockgw.start_mock("tcn", seed=7, units=1)
    try:
        summ = client.summary(config.get_settings(), host, mock=True)
    finally:
        mockgw.stop_mock("tcn")
    assert set(summ["circuit_names"]) == set(summ["circuits_on"])
    assert all(isinstance(v, str) and v for v in summ["circuit_names"].values())


def test_the_view_uses_the_aGates_names():
    state.reset_gateways()
    try:
        g = state.register_gateway("gcn", "127.0.0.1:9000", "aGate")
        g.last_summary = _summ(**{"1": "Circuit 1", "2": "Test Switch", "3": " "})
        names = [c["name"] for c in system_view.gateway_payload(g)["circuits"]]
        assert names == ["Circuit 1", "Test Switch", "Circuit 3"]      # blank: the default
        # Customise diagram's answer still wins, and the aGate's name is its placeholder
        raw = {"site": {}, "gateways": [system_view.gateway_payload(g)]}
        f = {x["key"]: x for x in sv.customise.fields(raw) if x["scope"] == "gcn"}
        assert f["circuit2_name"]["auto"] == "Test Switch"
        out = sv.customise.apply(raw, {"gcn": {"circuit2_name": "Pool"}})
        assert out["gateways"][0]["circuits"][1]["name"] == "Pool"
    finally:
        state.reset_gateways()
