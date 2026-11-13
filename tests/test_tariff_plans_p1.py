"""Tariff plans per meter, phase 1 (owner 2026-11-13, aligned with the Modbus Bridge):
one tariff in force per meter. A new or imported tariff closes the current one the day
before it starts and the meter points at the tariff in force today. An overlap is refused
(400). Import reuses the utility with the same retailer + network and carries
profile.effective_start / effective_end both ways."""
import datetime as dt

import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import app as app_module, config, environment, db
from franklinwh_direct_connect_bridge import tariff_plans
from franklinwh_direct_connect_bridge.db import MetricsStore

TODAY = dt.date(2026, 11, 13)


def _profile(name="AGL Battery Rewards", start=None, end=None):
    p = {"name": name, "retailer": "AGL Energy", "network": "Ausgrid", "plan_type": "tou",
         "country": "AU", "timezone": "Australia/Sydney",
         "pricing": {"billing_cycle_day": 2, "default_rate": {"buy": 0.2, "sell": 0.03}}}
    if start:
        p["effective_start"] = start
    if end:
        p["effective_end"] = end
    return {"type": "franklinwh-bridge/tariff-profile", "version": 1, "profile": p}


@pytest.fixture
def c(tmp_path, monkeypatch):
    store = MetricsStore(str(tmp_path / "m.db"))
    monkeypatch.setattr(environment, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "_settings", None)
    monkeypatch.setattr(db, "get_store", lambda s: store)
    monkeypatch.setattr(tariff_plans, "today", lambda: TODAY)
    store.create_site(sid="site1", name="Home", is_default=True) if hasattr(store, "create_site") else None
    store.create_meter(mid="m1", site_id="site1", is_default=True)
    client = TestClient(app_module.create_app())
    client.store = store
    return client


def _util(c):
    return c.post("/api/utilities", json={"name": "AGL Energy", "network_dnsp": "Ausgrid"}).json()["id"]


def _tariff(c, uid, name, start=None, end=None, meter="m1"):
    return c.post("/api/tariffs", json={"utility_id": uid, "name": name, "meter_id": meter,
                                        "effective_start": start, "effective_end": end})


def test_new_tariff_closes_the_current_one_and_repoints_the_meter(c):
    uid = _util(c)
    t1 = _tariff(c, uid, "Old", start="2026-09-14").json()
    assert c.store.meter("m1")["tariff_id"] == t1["id"]
    t2 = _tariff(c, uid, "New", start="2026-11-01").json()
    assert c.store.tariff(t1["id"])["effective_end"] == "2026-10-31"
    assert c.store.meter("m1")["tariff_id"] == t2["id"]


def test_future_tariff_leaves_today_on_the_old_one(c):
    uid = _util(c)
    t1 = _tariff(c, uid, "Old", start="2026-09-14").json()
    _tariff(c, uid, "Next", start="2026-12-01")
    assert c.store.tariff(t1["id"])["effective_end"] == "2026-11-30"
    assert c.store.meter("m1")["tariff_id"] == t1["id"]


def test_no_start_means_from_today(c):
    uid = _util(c)
    t1 = _tariff(c, uid, "Old", start="2026-09-14").json()
    t2 = _tariff(c, uid, "New").json()
    assert t2["effective_start"] == "2026-11-13"
    assert c.store.tariff(t1["id"])["effective_end"] == "2026-11-12"


def test_overlap_is_refused(c):
    uid = _util(c)
    _tariff(c, uid, "Old", start="2026-09-14", end="2026-10-31")
    r = _tariff(c, uid, "Clash", start="2026-10-01", end="2026-10-15")
    assert r.status_code == 400 and "Old" in r.json()["detail"]
    t = _tariff(c, uid, "Later", start="2026-11-01").json()
    r = c.patch(f"/api/tariffs/{t['id']}", json={"effective_start": "2026-10-20"})
    assert r.status_code == 400 and "Old" in r.json()["detail"]


def test_deleting_the_tariff_in_force_repoints_the_meter(c):
    uid = _util(c)
    t1 = _tariff(c, uid, "Old", start="2026-09-14").json()
    t2 = _tariff(c, uid, "New", start="2026-11-01").json()
    c.delete(f"/api/tariffs/{t2['id']}")
    assert c.store.meter("m1")["tariff_id"] is None      # Old ended 2026-10-31
    assert c.store.tariff(t1["id"])["effective_end"] == "2026-10-31"


def test_import_reuses_the_utility_and_closes_the_current_plan(c):
    a = c.post("/api/tariffs/import", json=_profile("Plan A", start="2026-09-14")).json()
    b = c.post("/api/tariffs/import", json=_profile("Plan B", start="2026-11-01")).json()
    assert a["utility_id"] == b["utility_id"]
    assert len(c.store.utilities()) == 1
    assert c.store.tariff(a["tariff_id"])["effective_end"] == "2026-10-31"
    assert c.store.meter("m1")["tariff_id"] == b["tariff_id"]
    prof = c.get(f"/api/tariffs/{a['tariff_id']}/export").json()["profile"]
    assert prof["effective_start"] == "2026-09-14" and prof["effective_end"] == "2026-10-31"


def test_import_preview_says_what_it_replaces(c):
    c.post("/api/tariffs/import", json=_profile("Plan A", start="2026-09-14"))
    pv = c.post("/api/tariffs/import?dry_run=true", json=_profile("Plan B")).json()["preview"]
    assert pv["replaces"] == "Plan A" and pv["reuses_utility"] is True
    assert pv["effective_start"] == "2026-11-13"


def test_meter_edit_assigns_the_tariff_to_that_meter(c):
    uid = _util(c)
    t = c.post("/api/tariffs", json={"utility_id": uid, "name": "Loose"}).json()
    c.patch("/api/meters/m1", json={"utility_id": uid, "tariff_id": t["id"]})
    assert c.store.tariff(t["id"])["meter_id"] == "m1"


def test_migration_backfills_meter_id(tmp_path):
    st = MetricsStore(str(tmp_path / "x.db"))
    st.create_utility(uid="u", name="X")
    st.create_tariff(tid="t", utility_id="u", name="T")
    st.create_meter(mid="mm", site_id="s", tariff_id="t")
    st._conn.execute("UPDATE tariffs SET meter_id=NULL"); st._conn.commit()
    st._migrate_tariff_meter()
    assert st.tariff("t")["meter_id"] == "mm"


def test_ui_saves_against_a_meter_and_keeps_errors_in_the_form():
    import pathlib
    pkg = pathlib.Path(app_module.__file__).parent
    js = (pkg / "static" / "js" / "settings_tab.js").read_text()
    html = (pkg / "templates" / "tabs" / "settings.html").read_text()
    save = js[js.index("async saveTariff()"):js.index("async deleteTariff(t)")]
    assert "meter_id" in save and "toast(" not in save
    assert "tariffMsg" in save and "saveTariffAsNew" in js
    sup = js[js.index("async supersedeTariff(t)"):js.index("newUtility()")]
    assert "method: 'PATCH'" not in sup           # the server closes the old plan now
    assert 'data-testid="tariff-msg"' in html and "saveTariffAsNew()" in html
