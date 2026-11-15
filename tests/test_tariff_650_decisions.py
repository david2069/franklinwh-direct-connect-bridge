"""#650 owner decisions (2026-11-16) and #667.

- On a one-meter install, a tariff on no meter goes onto that meter by itself, when its
  dates don't clash with the meter's plans.
- "+ New retailer" in the tariff editor makes the retailer only when the tariff is saved,
  so Cancel leaves nothing behind.
- #667: closing the editor raised "Cannot read properties of null (reading 'buy')"; an
  import with demand off kept the demand window.
"""
import pathlib

from franklinwh_direct_connect_bridge import tariff_io, tariff_plans
from franklinwh_direct_connect_bridge.db import MetricsStore

PKG = pathlib.Path(__file__).resolve().parents[1] / "src" / "franklinwh_direct_connect_bridge"
HTML = (PKG / "templates" / "partials" / "plans_meters.html").read_text()
JS = (PKG / "static" / "js" / "settings_tab.js").read_text()


def _store(tmp_path, meters=1):
    st = MetricsStore(str(tmp_path / "m.db"))
    st.create_site(sid="s1", name="Home", is_default=True)
    for i in range(meters):
        st.create_meter(mid=f"m{i + 1}", site_id="s1", name=f"Meter {i + 1}", is_default=i == 0)
    st.create_utility(uid="u1", name="AGL Energy")
    return st


def test_a_tariff_on_no_meter_goes_on_the_only_meter(tmp_path):
    st = _store(tmp_path)
    st.create_tariff(tid="t1", utility_id="u1", name="Service 1")
    assert tariff_plans.adopt_orphans(st) == ["t1"]
    assert st.tariff("t1")["meter_id"] == "m1"
    assert st.meter("m1")["tariff_id"] == "t1"


def test_not_when_its_dates_clash_or_there_are_two_meters(tmp_path):
    st = _store(tmp_path)
    st.create_tariff(tid="t1", utility_id="u1", name="Old", meter_id="m1")
    st.create_tariff(tid="t2", utility_id="u1", name="Loose")       # current vs current: clash
    assert tariff_plans.adopt_orphans(st) == []
    assert st.tariff("t2")["meter_id"] is None
    st2 = _store(tmp_path / "two", meters=2)
    st2.create_tariff(tid="t3", utility_id="u1", name="Which meter?")
    assert tariff_plans.adopt_orphans(st2) == []


def test_the_bridge_adopts_them_on_start_and_on_create():
    app = (PKG / "app.py").read_text()
    assert app.count("tariff_plans.adopt_orphans(") >= 2


def test_new_retailer_from_the_tariff_editor_waits_for_save():
    assert 'data-testid="tariff-new-retailer"' in HTML and "newUtility(true)" in HTML
    a = JS.index("async saveUtility()")
    save_util = JS[a:JS.index("async deleteUtility(", a)]
    assert "forTariff" in save_util and "pendingUtility" in save_util
    a = JS.index("async saveTariff()")
    save_tariff = JS[a:JS.index("async saveTariffAsNew()", a)]
    assert "pendingUtility" in save_tariff and "'api/utilities'" in save_tariff
    assert "method: 'DELETE'" in save_tariff          # a refused tariff leaves no retailer


def test_closing_the_editor_does_not_read_a_rate_of_nothing():
    a = JS.index("get defaultRate()")
    getter = JS[a:JS.index("get season()", a)]
    assert "return null" not in getter


def test_an_import_with_demand_off_has_no_demand_window():
    prof = {"name": "Service 1", "retailer": "AGL Energy", "network": "Ausgrid", "plan_type": "tou",
            "has_tou": 1, "has_peak_demand": 0, "has_export_bonus": 0,
            "demand_window": {"months": [], "days": [], "start": "14:00", "end": "20:00"},
            "pricing": {"billing_cycle_day": 2, "demand_rate": 0, "seasons": []}}
    _util, tar, _tz = tariff_io.to_local(prof)
    assert not tar.get("demand_window")
    prof["has_peak_demand"], prof["pricing"]["demand_rate"] = 1, 12.5
    assert tariff_io.to_local(prof)[1]["demand_window"]["start"] == "14:00"
