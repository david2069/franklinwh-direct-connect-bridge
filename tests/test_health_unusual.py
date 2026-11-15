"""Scheduled health check, phase 3: unusual-change flags in the daily report (owner
2026-11-15; the Modbus bridge's design, from this bridge's daily snapshot). Yesterday
against the median of the 28 days before; at least 7 needed. Only a drop in SoH or
efficiency turns the report amber."""

import datetime as dt

import pytest

from franklinwh_direct_connect_bridge import health_report as hr, workers
from franklinwh_direct_connect_bridge.db import MetricsStore

GWS = [{"id": "gw1", "name": "Home"}]


@pytest.fixture
def st(tmp_path):
    s = MetricsStore(str(tmp_path / "m.db"))
    hr.set_weekly(s, False)
    yield s
    s.close()


def ts(day, hh=0, mm=0):
    return dt.datetime.strptime(f"{day} {hh:02d}:{mm:02d}", "%Y-%m-%d %H:%M").timestamp()


def days_before(day: str, n: int) -> list[str]:
    d = dt.date.fromisoformat(day)
    return [(d - dt.timedelta(days=i)).isoformat() for i in range(n, 0, -1)]


def seed(st, day, n=20, **last):
    """``n`` ordinary days before ``day``, then ``day`` with ``last`` changed."""
    base = {"soh": 96.0, "soc": 50, "battery_charged_wh": 10000.0, "battery_discharged_wh": 9000.0,
            "solar_wh": 20000.0, "grid_import_wh": 3000.0, "grid_export_wh": 8000.0,
            "load_wh": 14000.0, "alerts": 0}
    for d in days_before(day, n):
        st.save_health_snapshot({"gateway_id": "gw1", "day": d, "ts": ts(d, 23), **base})
        st.save_health_snapshot({"gateway_id": "", "day": d, "ts": ts(d, 23), "alerts": 0,
                                 "log_warnings": 4, "log_errors": 0})
    st.save_health_snapshot({"gateway_id": "gw1", "day": day, "ts": ts(day, 23),
                             **{**base, **{k: v for k, v in last.items() if k not in ("log_warnings", "log_errors")}}})
    st.save_health_snapshot({"gateway_id": "", "day": day, "ts": ts(day, 23), "alerts": 0,
                             "log_warnings": last.get("log_warnings", 4), "log_errors": last.get("log_errors", 0)})


def test_an_ordinary_day_has_no_flags(st):
    seed(st, "2026-11-15")
    u = hr.unusual(st, GWS, "2026-11-15")
    assert u["flags"] == [] and u["checked"] > 0


def test_a_soh_drop_flags_and_grades(st):
    seed(st, "2026-11-15", soh=94.5)
    f = hr.unusual(st, GWS, "2026-11-15")["flags"]
    assert [(x["metric"], x["direction"], x["grades"]) for x in f] == [("soh", "drop", True)]
    assert f[0]["text"] == "Home: SoH down, 94.5% (usual 96%)"


def test_an_unusual_energy_day_flags_without_grading(st):
    seed(st, "2026-11-15", grid_import_wh=9000.0)
    f = hr.unusual(st, GWS, "2026-11-15")["flags"]
    assert [(x["metric"], x["direction"], x["grades"]) for x in f] == [("grid_import_wh", "high", False)]
    assert f[0]["text"] == "Home: grid import high, 9.0 kWh (usual 3.0 kWh)"


def test_too_few_days_to_compare_checks_nothing(st):
    seed(st, "2026-11-15", n=5, soh=90.0)
    assert hr.unusual(st, GWS, "2026-11-15") == {"day": "2026-11-15", "checked": 0, "flags": []}


def test_the_daily_report_carries_them_and_only_a_drop_turns_it_amber(st):
    seed(st, "2026-11-14", grid_import_wh=9000.0, log_warnings=40)
    r = hr.build_daily(st, ts("2026-11-15", 7), registry=workers.Registry(), gateways=GWS)
    assert {f["metric"] for f in r["unusual"]["flags"]} == {"grid_import_wh", "log_warnings"}
    assert r["level"] == "green"
    title, msg = hr.notification_text(r)
    assert "Unusual yesterday:" in msg and "grid import high" in msg

    st2 = MetricsStore(":memory:")
    seed(st2, "2026-11-14", soh=94.0)
    r = hr.build_daily(st2, ts("2026-11-15", 7), registry=workers.Registry(), gateways=GWS)
    assert r["level"] == "amber" and r["reasons"][0].startswith("Home: SoH down")
