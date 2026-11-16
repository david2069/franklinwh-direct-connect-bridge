"""#698 phases 2-4: one extra read every 60 s (1411 smart-circuit and V2L metering, 1901
generator) in the poll's own session, as scheduler sensors. A failed read leaves the values
None and never fails the poll."""
import pathlib
from types import SimpleNamespace

from franklinwh_direct_connect_bridge import circuits, client, poller
from franklinwh_direct_connect_bridge import scheduler as sch

ROOT = pathlib.Path(__file__).resolve().parents[1] / "src/franklinwh_direct_connect_bridge"

METER = {"Sw1Volt": 2301, "SW1Curr": 4, "SW1ExpPower": 920, "SW1ExpEnergy": 12345,
         "Sw2Volt": 2302, "SW2Curr": 0, "SW2ExpPower": 0, "SW2ExpEnergy": 500,
         "CarSWPower": 1500, "CarSWExpEnergy": 2000, "CarSWImpEnergy": 300}
GEN = {"genEn": 1, "genStat": 1, "genRatedPower": 7500, "genModel": "G1"}
CFG = {"Sw1Mode": 1, "Sw2Mode": 0, "Sw3Mode": 0, "CarSwConsSupEnable": 1}


class FakeClient:
    def __init__(self, meter=METER, gen=GEN, fail=()):
        self.meter, self.gen, self.fail = meter, gen, fail

    def smart_circuit_meter(self):
        if "meter" in self.fail:
            raise OSError("timed out")
        return self.meter

    def generator(self):
        if "gen" in self.fail:
            raise TimeoutError()
        return self.gen


SETTINGS = SimpleNamespace(smart_circuit_count="auto")


def test_extras_read_meter_and_generator_in_the_session():
    ex = client.device_extras(FakeClient(), SETTINGS, {}, CFG)
    assert ex["meter"][1]["watts"] == 920 and ex["meter"][1]["energy_lifetime_kwh"] == 123.45
    assert ex["carsw"]["watts"] == 1500
    assert ex["generator"]["state"] == 1 and ex["generator"]["enabled"] is True
    assert isinstance(ex["circuit_count"], int)


def test_a_failed_read_is_none_and_never_raises():
    ex = client.device_extras(FakeClient(fail=("meter", "gen")), SETTINGS, {}, CFG)
    assert ex["meter"] is None and ex["carsw"] is None and ex["generator"] is None
    snap = sch.device_snapshot({}, ex)
    for sid in ("circuit.1.power_w", "circuit.1.today_kwh", "v2l.power_w",
                "generator.state", "generator.enabled", "generator.rated_kw"):
        assert snap[sid] is None, sid


def test_snapshot_values():
    ex = client.device_extras(FakeClient(), SETTINGS, {}, CFG)
    ex["today_kwh"] = {"1": 1.5, "2": None}
    snap = sch.device_snapshot({"carsw_enabled": True}, ex)
    assert snap["circuit.1.power_w"] == 920 and snap["circuit.2.power_w"] == 0
    assert snap["circuit.1.today_kwh"] == 1.5 and snap["circuit.2.today_kwh"] is None
    assert snap["circuit.3.power_w"] is None           # no meter channel: no reading
    assert snap["circuit.count"] == ex["circuit_count"]
    assert snap["v2l.power_w"] == 1500
    assert snap["v2l.export_kwh"] == 20.0 and snap["v2l.import_kwh"] == 3.0
    assert snap["generator.enabled"] == 1 and snap["generator.state"] == 1
    assert snap["generator.state_desc"] == "Running / ON" and snap["generator.rated_kw"] == 7.5
    assert sch.evaluate([{"sensor": "generator.state", "op": "==", "value": 1}], snap)


def test_today_kwh_counts_from_the_first_reading_of_the_site_day():
    base, today = circuits.today_kwh(None, "2026-11-17", {"1": 100.0, "2": None})
    assert today == {"1": 0.0, "2": None}
    base, today = circuits.today_kwh(base, "2026-11-17", {"1": 101.25, "2": 5.0})
    assert today["1"] == 1.25 and today["2"] == 0.0   # 2 first read now
    base, today = circuits.today_kwh(base, "2026-11-18", {"1": 102.0, "2": 6.0})
    assert today == {"1": 0.0, "2": 0.0}               # a new day starts again
    base, today = circuits.today_kwh(base, "2026-11-18", {"1": 3.0, "2": 6.5})
    assert today["1"] == 0.0 and today["2"] == 0.5     # a counter reset rebaselines


def test_new_sensors_listed_named_and_greyed():
    ids = sch.known_sensor_ids()
    for sid in ("circuit.1.power_w", "circuit.1.today_kwh", "circuit.count", "v2l.power_w",
                "v2l.export_kwh", "v2l.import_kwh", "generator.enabled", "generator.state",
                "generator.state_desc", "generator.rated_kw"):
        assert sid in ids and sch.sensor_feature(sid) == "gateway", sid
    rows = {r["id"]: r for r in sch.device_sensor_rows({1: ["Pool pump"]})}
    assert rows["circuit.1.power_w"]["label"].startswith("Smart circuit 1 (Pool pump):")
    assert rows["circuit.count"]["group"] == "Smart Circuits"
    acc = {"circuits": 2, "generator": False, "v2l": False}
    assert sch.device_inactive("circuit.3.power_w", acc) == "not installed"
    assert sch.device_inactive("circuit.count", acc) is None
    assert sch.device_inactive("generator.state", acc) == "not installed"
    assert sch.device_inactive("v2l.power_w", acc) == "not installed"


def test_the_poller_reads_them_every_60_seconds_in_its_own_session():
    assert poller.DEVICE_EXTRAS_EVERY_S == 60
    src = (ROOT / "poller.py").read_text()
    assert "extras=" in src and "gw.device_extras" in src
    assert "extras: bool = False" in (ROOT / "client.py").read_text()
