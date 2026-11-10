"""Billing engine Phase 1 — tariff.*_window_active sensors. Window matcher + snapshot.
Informational (express-don't-enforce): None when a window isn't configured."""
import datetime as dt
from franklinwh_direct_connect_bridge.db import MetricsStore
from franklinwh_direct_connect_bridge import scheduler as sch


def test_in_window_same_day_and_wrap():
    w_day = {"start": "15:00", "end": "21:00"}
    assert sch._in_window(w_day, dt.datetime(2026, 9, 24, 16, 0)) is True
    assert sch._in_window(w_day, dt.datetime(2026, 9, 24, 21, 0)) is False   # end exclusive
    assert sch._in_window(w_day, dt.datetime(2026, 9, 24, 14, 59)) is False
    w_wrap = {"start": "22:00", "end": "06:00"}                              # overnight
    assert sch._in_window(w_wrap, dt.datetime(2026, 9, 24, 23, 0)) is True
    assert sch._in_window(w_wrap, dt.datetime(2026, 9, 24, 5, 0)) is True
    assert sch._in_window(w_wrap, dt.datetime(2026, 9, 24, 12, 0)) is False


def test_in_window_month_and_day_filters():
    w = {"months": [12, 1, 2], "days": [0, 1, 2, 3, 4], "start": "16:00", "end": "20:00"}
    assert sch._in_window(w, dt.datetime(2026, 1, 6, 17, 0)) is True         # Jan, Tue
    assert sch._in_window(w, dt.datetime(2026, 6, 2, 17, 0)) is False        # wrong month
    assert sch._in_window(w, dt.datetime(2026, 1, 4, 17, 0)) is False        # Sunday
    # empty months/days = all; no time bound = whole day
    assert sch._in_window({}, dt.datetime(2026, 1, 1, 3, 0)) is True


def _store_with_tariff(tmp_path, **windows):
    st = MetricsStore(str(tmp_path / "m.db"))
    st.ensure_default_site_meter()
    st.create_utility(uid="u1", name="AGL")
    st.create_tariff(tid="t1", utility_id="u1", name="TOU",
                     pricing={"default_rate": {"buy": 0.3, "sell": 0.08},
                              "import_windows": windows.pop("import_windows", [])},
                     **windows)
    m = next(x for x in st.meters() if x.get("is_default"))
    st.update_meter(m["id"], tariff_id="t1")
    return st


def test_billing_snapshot_windows_active(tmp_path):
    st = _store_with_tariff(
        tmp_path,
        demand_window={"start": "15:00", "end": "21:00"},
        bonus_window={"start": "10:00", "end": "14:00"},
    )
    now = dt.datetime(2026, 9, 24, 16, 0)                       # in demand, not in bonus
    snap = sch.billing_snapshot(st, None, now)
    assert snap["tariff.demand_window_active"] == 1
    assert snap["tariff.bonus_window_active"] == 0
    # charge/import not configured on this tariff → None (fails closed on a gate)
    assert snap["tariff.export_charge_window_active"] is None
    assert snap["tariff.import_window_active"] is None


def test_billing_snapshot_import_windows(tmp_path):
    st = _store_with_tariff(tmp_path, import_windows=[{"start": "00:00", "end": "06:00"}])
    assert sch.billing_snapshot(st, None, dt.datetime(2026, 9, 24, 3, 0))["tariff.import_window_active"] == 1
    assert sch.billing_snapshot(st, None, dt.datetime(2026, 9, 24, 9, 0))["tariff.import_window_active"] == 0


def test_billing_snapshot_empty_without_tariff(tmp_path):
    st = MetricsStore(str(tmp_path / "m.db"))
    st.ensure_default_site_meter()                              # meter, but no tariff attached
    assert sch.billing_snapshot(st, None, dt.datetime(2026, 9, 24, 16, 0)) == {}


def test_billing_sensors_in_picker(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from franklinwh_direct_connect_bridge import app as app_module, config, environment, db
    st = _store_with_tariff(tmp_path, demand_window={"start": "15:00", "end": "21:00"})
    monkeypatch.setattr(environment, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "_settings", None)
    monkeypatch.setattr(db, "get_store", lambda s: st)
    ids = {s["id"]: s["group"] for s in TestClient(app_module.create_app()).get("/api/schedules").json()["sensors"]}
    assert ids.get("tariff.demand_window_active") == "Tariff & Utility"
    assert ids.get("tariff.import_window_active") == "Tariff & Utility"
