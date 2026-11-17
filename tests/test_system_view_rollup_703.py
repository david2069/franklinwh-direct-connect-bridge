"""#703 (owner 2026-11-17): with several aPowers, System view shows one battery with the
count and the aGate's totals, and hover or click lists each aPower. The count came only from
1301 (``devNum``/``fhpSn``), which this firmware and the mock leave out, so a 4-aPower gateway
said "Battery". Each aPower's SoC, SoH, current and BMS state are read in the 60 s device
read (#700), with the Battery tab's reads (1705 + 1835)."""
import pathlib
import tomllib
from types import SimpleNamespace

from franklinwh_direct_connect_bridge import client, config, mockgw, state, system_view
import franklinwh_system_view as sv

ROOT = pathlib.Path(__file__).resolve().parents[1]
SNS = ["MFHP0000000000000001", "MFHP0000000000000002", "MFHP0000000000000003",
       "MFHP0000000000000004"]


def test_the_count_comes_from_the_login_manifest_when_1301_has_none():
    b = client._battery_from_power_flow({"soc": 64.0}, {"FHP_SN": SNS})
    assert b["count"] == 4
    # 1301's own count still wins, and nothing to go on stays None
    assert client._battery_from_power_flow({"devNum": 2}, {"FHP_SN": SNS})["count"] == 2
    assert client._battery_from_power_flow({}, {})["count"] is None


def test_a_four_apower_mock_reports_four():
    host = mockgw.start_mock("t703", seed=7, units=4)
    try:
        summ = client.summary(config.get_settings(), host, mock=True, extras=True)
    finally:
        mockgw.stop_mock("t703")
    assert summ["battery"]["count"] == 4
    units = summ["device_extras"]["apowers"]
    assert [u["id"] for u in units] == [1, 2, 3, 4]
    assert all(isinstance(u["soc_pct"], float) for u in units)


class FakeClient:
    def __init__(self, fail=()):
        self.fail = fail

    def device_ids(self):
        return [1, 2]

    def battery_cells(self, dev_id):
        if ("cells", dev_id) in self.fail:
            raise OSError("timed out")
        return {"batSoc": 60.0 + dev_id, "batSoh": 95.0, "currGrp": -4.5}

    def device_states(self, dev_id):
        if ("states", dev_id) in self.fail:
            raise TimeoutError()
        return {"bmsState": 5}

    def smart_circuit_meter(self):
        raise OSError("not here")

    def generator(self):
        raise OSError("not here")


def test_each_apower_is_read_in_the_device_read():
    ex = client.device_extras(FakeClient(), SimpleNamespace(smart_circuit_count="auto"), {}, None)
    a1, a2 = ex["apowers"]
    assert a1 == {"id": 1, "soc_pct": 61.0, "soh_pct": 95.0, "current_a": 4.5,
                  "status": a1["status"]} and isinstance(a1["status"], str) and a1["status"]


def test_a_failed_unit_read_leaves_what_it_could_read():
    ex = client.device_extras(FakeClient(fail={("cells", 1), ("states", 2)}),
                              SimpleNamespace(smart_circuit_count="auto"), {}, None)
    a1, a2 = ex["apowers"]
    assert a1["soc_pct"] is None and a1["status"]
    assert a2["soc_pct"] == 62.0 and a2["status"] is None


def _gw(count, apowers):
    g = state.register_gateway("g703", "127.0.0.1:9000", "aGate")
    g.last_summary = {"ok": True, "power": {"soc": 64.0, "battery_w": 200},
                      "battery": {"soc": 64.0, "count": count}}
    g.device_extras = {"apowers": apowers}
    return g


UNITS = [{"id": i, "soc_pct": 60.0, "soh_pct": 95.0, "current_a": 4.5, "status": "Discharging"}
         for i in (1, 2, 3, 4)]


def test_several_apowers_are_one_battery_with_a_line_each():
    state.reset_gateways()
    try:
        bat = system_view.gateway_payload(_gw(4, UNITS))["battery"]
        assert bat["rollup"] is True and bat["count"] == 4
        assert [u["name"] for u in bat["units"]] == ["aP1", "aP2", "aP3", "aP4"]
        sc = sv.scene(system_view.gateway_payload(_gw(4, UNITS)))
        b = [n for n in sc["nodes"] if n["icon"] == "apower"]
        assert len(b) == 1 and b[0]["label"] == "Batteries ×4"
        assert b[0]["hover"].count("\n") == 4
    finally:
        state.reset_gateways()


def test_one_apower_or_no_unit_reads_draw_as_before():
    state.reset_gateways()
    try:
        assert "rollup" not in system_view.gateway_payload(_gw(1, UNITS[:1]))["battery"]
        bat = system_view.gateway_payload(_gw(4, []))["battery"]
        assert "rollup" not in bat and bat["count"] == 4
    finally:
        state.reset_gateways()


def test_the_pin_is_the_release_with_the_rollup():
    deps = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["dependencies"]
    assert "franklinwh-system-view==0.4.1" in deps
