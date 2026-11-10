"""#205 — a history row names the gateway whose tick wrote it."""
import datetime as dt

from franklinwh_direct_connect_bridge import scheduler as sch
from franklinwh_direct_connect_bridge.db import MetricsStore


def test_an_all_scope_rule_writes_one_row_per_named_gateway(tmp_path):
    st = MetricsStore(str(tmp_path / "m.db"))
    st.create_schedule(sid="a1", name="site-wide", spec={
        "fire_at": "12:00", "duration_min": 60, "gateway_scope": "all",
        "conditions": [{"sensor": "battery.soc_pct", "op": "<", "value": 20}],
        "action": {"kind": "set_mode", "mode": "self"}})
    sch._window_inside.clear(); sch._window_key.clear(); sch._gated_day.clear()
    now = dt.datetime(2026, 10, 21, 12, 5)
    for gw in ("gw-a", "gw-b"):                 # each gateway's tick, SoC too high on both
        sch.tick(settings=None, client=None, store=st, state={"soc": 50}, host="h",
                 gateway_id=gw, now=now, modbus_host="")
    gated = [e for e in st.schedule_log(schedule_id="a1") if e["status"] == "gated"]
    assert sorted(e["gateway_id"] for e in gated) == ["gw-a", "gw-b"]


def test_an_existing_log_gains_the_column(tmp_path):
    import sqlite3
    path = str(tmp_path / "old.db")
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE schedule_log(id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT "
                "NULL, schedule_id TEXT NOT NULL, name TEXT, status TEXT, result TEXT)")
    con.execute("INSERT INTO schedule_log(ts, schedule_id, name, status, result) "
                "VALUES (1, 's', 'n', 'fired', 'ok')")
    con.commit(); con.close()
    rows = MetricsStore(path).schedule_log()
    assert rows[0]["gateway_id"] == "" and rows[0]["status"] == "fired"
