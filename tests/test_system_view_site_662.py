"""#662: every gateway of a site in one System view diagram. Each gateway's site comes from
its meter's site (gateways.meter_id → meters.site_id); franklinwh-system-view 0.4.0 draws the
gateways that share a site together."""
import pytest

from franklinwh_direct_connect_bridge import state, system_view
from franklinwh_direct_connect_bridge.db import MetricsStore

from test_system_view_428 import gw, us_summary


@pytest.fixture(autouse=True)
def _clean():
    state.reset_gateways()
    yield
    state.reset_gateways()


@pytest.fixture
def store(tmp_path):
    st = MetricsStore(str(tmp_path / "m.db"))
    st.create_site(sid="s1", name="Home", is_default=True)
    st.create_site(sid="s2", name="Farm")
    st.create_meter(mid="m1", site_id="s1", name="Meter 1", ac_type="three", rated_amps=63)
    st.create_meter(mid="m2", site_id="s2", name="Shed meter")
    for gid, label, mid in (("gw1", "aGate 1", "m1"), ("gw2", "aGate 2", "m1"),
                            ("gw3", "Shed", "m2"), ("gw4", "Loose", None)):
        st.create_gateway(gw_id=gid, label=label, host="127.0.0.1")
        if mid:
            st.update_gateway(gid, meter_id=mid)
        gw(gid, us_summary(), label=label)
    return st


def test_each_gateway_carries_its_meters_site(store):
    by = {g["id"]: g for g in system_view.raw_payload(store=store)["gateways"]}
    assert by["gw1"]["site"] == {"id": "s1", "name": "Home",
                                 "meter": {"id": "m1", "name": "Meter 1", "ac": "three", "rated_amps": 63.0}}
    assert by["gw2"]["site"]["id"] == "s1"
    assert by["gw3"]["site"] == {"id": "s2", "name": "Farm",
                                 "meter": {"id": "m2", "name": "Shed meter", "ac": "single", "rated_amps": None}}
    assert "site" not in by["gw4"]                     # no meter: no site, drawn on its own


def test_the_gateways_of_one_site_are_one_diagram(store):
    import franklinwh_system_view as sv
    out = sv.build(system_view.raw_payload(store=store))
    assert [(s["id"], s["gateway_ids"]) for s in out["site_groups"]] == [("s1", ["gw1", "gw2"])]
    land = out["site_groups"][0]["scenes"]["landscape"]
    assert [n["pick"] for n in land["nodes"] if n.get("pick")] == ["gw1", "gw2"]
    assert next(n for n in land["nodes"] if n["id"] == "meter")["status"] == "3 × 63 A"
