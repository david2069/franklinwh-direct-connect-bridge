"""FranklinWH TOU schedule from the Cloud API (owner 2026-11-16): a dated copy taken at
start-up and when TOU mode is set, the bridge's schedules that clash with it while TOU is
on, and an import into the bridge's own schedules, which the bridge recommends instead.
Read-only towards the cloud: ``get_tou_dispatch_detail`` only."""
import datetime as dt

import pytest

from franklinwh_direct_connect_bridge import cloud_tou
from franklinwh_direct_connect_bridge.db import MetricsStore


def blk(start, end, dispatch, wave=1, **kw):
    return {"name": "x", "startHourTime": start, "endHourTime": end, "waveType": wave,
            "dispatchId": dispatch, **kw}


def detail(summer_weekdays=None):
    """``getTouDispatchDetail``'s result, cut down: two seasons, weekdays and weekends."""
    wd = summer_weekdays or [blk("00:00", "02:00", 6, 0), blk("02:00", "05:00", 8, 4),
                             blk("05:00", "15:00", 6, 1), blk("15:00", "21:00", 1, 2),
                             blk("21:00", "24:00", 7, 2, maxChargeSoc=None)]
    return {
        "template": {"name": "EA116 TOU", "electricCompany": "Amber Electric",
                     "updateTime": "2026-03-19 13:44:38", "workMode": 1},
        "strategyList": [
            {"seasonName": "Summer", "month": "10,11,12,1,2,3",
             "dayTypeVoList": [
                 {"dayName": "Weekdays", "dayType": 1, "detailVoList": wd},
                 {"dayName": "Weekends,Holidays", "dayType": 2,
                  "detailVoList": [blk("00:00", "24:00", 6, 0)]}]},
            {"seasonName": "Winter", "month": "4,5,6,7,8,9",
             "dayTypeVoList": [
                 {"dayName": "Everyday", "dayType": 3,
                  "detailVoList": [blk("00:00", "02:00", 6, 0), blk("02:00", "05:00", 8, 4),
                                   blk("05:00", "24:00", 6, 1)]}]},
        ],
        "detailDefaultVo": {"touDispatchList": []},
    }


MON = dt.datetime(2026, 11, 16, 12, 0)       # a Monday in summer
SAT = dt.datetime(2026, 11, 21, 12, 0)


# ── the schedule ─────────────────────────────────────────────────────────────
def test_the_schedule_reads_seasons_days_and_blocks():
    s = cloud_tou.schedule(detail())
    assert s["name"] == "EA116 TOU" and s["utility"] == "Amber Electric"
    assert s["cloud_updated"] == "2026-03-19 13:44:38"
    summer = s["seasons"][0]
    assert summer["months"] == [10, 11, 12, 1, 2, 3]
    assert summer["days"][0]["weekdays"] == [0, 1, 2, 3, 4]
    assert summer["days"][1]["weekdays"] == [5, 6]
    b = summer["days"][0]["blocks"][1]
    assert b == {"start": "02:00", "end": "05:00", "dispatch_id": 8,
                 "dispatch": "aPower charges from solar/grid", "wave": "Super off-peak"}
    assert s["seasons"][1]["days"][0]["weekdays"] == [0, 1, 2, 3, 4, 5, 6]


def test_blocks_on_a_day_follow_its_season_and_day_type():
    s = cloud_tou.schedule(detail())
    assert [b["dispatch_id"] for b in cloud_tou.blocks_on(s, MON.date())] == [6, 8, 6, 1, 7]
    assert [b["dispatch_id"] for b in cloud_tou.blocks_on(s, SAT.date())] == [6]
    assert len(cloud_tou.blocks_on(s, dt.date(2026, 6, 13))) == 3          # winter, every day


# ── the dated copy ───────────────────────────────────────────────────────────
def test_sync_keeps_a_dated_copy_and_a_new_one_only_when_it_changes(tmp_path, monkeypatch):
    st = MetricsStore(str(tmp_path / "m.db"))
    got = [detail()]
    monkeypatch.setattr(cloud_tou, "read", lambda settings, serial: got[0])
    a = cloud_tou.sync(st, None, "gw1", "SN1", "start", now=1000.0)
    assert a["changed"] and a["first_ts"] == 1000.0 and a["reason"] == "start"
    b = cloud_tou.sync(st, None, "gw1", "SN1", "tou-mode", now=2000.0)
    assert not b["changed"] and b["id"] == a["id"] and b["checked_ts"] == 2000.0
    got[0] = detail([blk("00:00", "24:00", 6, 0)])
    c = cloud_tou.sync(st, None, "gw1", "SN1", "manual", now=3000.0)
    assert c["changed"] and c["id"] != a["id"]
    hist = st.cloud_tou_history("gw1")
    assert [h["first_ts"] for h in hist] == [3000.0, 1000.0]
    assert cloud_tou.latest(st, "gw1")["schedule"]["seasons"][0]["days"][0]["blocks"][0]["end"] == "24:00"
    st.close()


@pytest.mark.parametrize("mode, prev, synced, want", [
    ("Self-Consumption", "", False, "start"),          # first cloud pass after start-up
    ("Self-Consumption", "Self-Consumption", True, None),
    ("Time-of-Use", "Self-Consumption", True, "tou-mode"),  # TOU mode was set
    ("Time-of-Use", "Time-of-Use", True, None),
    ("Time-of-Use ", "Emergency Backup", True, "tou-mode"),  # the library's trailing space
])
def test_when_to_take_a_copy(mode, prev, synced, want):
    assert cloud_tou.sync_reason(mode, prev, synced) == want


# ── clashes with the bridge's schedules ──────────────────────────────────────
def entry(sid, kind, start, dur, gw="gw1", direction="charge", **kw):
    action = {"kind": kind, **({"direction": direction, "power": 50, "unit": "pct"} if kind == "force" else {}),
              **({"mode": "backup"} if kind == "set_mode" else {})} if kind else {}
    return {"id": sid, "name": sid, "enabled": True, "gateway_id": gw, "fire_at": start,
            "duration_min": dur, "action": action, **kw}


def test_a_clash_is_a_force_that_contradicts_the_tou_blocks_dispatch():
    """Owner 2026-11-16: clashes are battery dispatch only, where they contradict. Summer
    weekdays: 00-02 self, 02-05 grid charge, 05-15 self, 15-21 to home, 21-24 export."""
    s = cloud_tou.schedule(detail())
    entries = [entry("charge-cheap", "force", "03:00", 60),                     # 8 + charge: ok
               entry("export-evening", "force", "22:00", 60, direction="discharge"),   # 7: ok
               entry("charge-peak", "force", "16:00", 60),                       # 1 + charge
               entry("hold", "force", "03:00", 30, direction="standby"),         # 8 + standby
               entry("storm", "set_mode", "00:00", 1440),                        # a mode: never
               entry("porch-light", "smart_circuit", "18:00", 60),
               entry("off", "force", "16:00", 60, enabled=False),
               entry("other-gw", "force", "16:00", 60, gw="gw2")]
    rows = cloud_tou.conflicts(s, entries, MON, "gw1")
    assert [(r["schedule_id"], r["force"], r["tou_dispatch_id"], r["start"], r["end"]) for r in rows] == [
        ("hold", "standby", 8, "03:00", "03:30"),
        ("charge-peak", "charge", 1, "16:00", "17:00")]
    assert rows[0]["tou_dispatch"] == "aPower charges from solar/grid" and rows[0]["slots"] == 1


def test_a_repeating_schedule_is_one_row_per_tou_block():
    s = cloud_tou.schedule(detail())
    every15 = entry("storm-charge", "force", "00:00", 6, trigger_type="interval",
                    interval_min=15, anchor="00:00")
    rows = cloud_tou.conflicts(s, [every15], MON, "gw1")
    assert [(r["tou_dispatch_id"], r["start"], r["end"], r["slots"]) for r in rows] == [
        (6, "00:00", "01:51", 8), (6, "05:00", "14:51", 40), (1, "15:00", "20:51", 24),
        (7, "21:00", "23:51", 12)]                          # 02:00-05:00 is grid charge: ok
    assert all(r["repeats"] == "every 15 min" for r in rows)


# ── import into the bridge's schedules ───────────────────────────────────────
def test_import_turns_the_charge_and_export_blocks_into_schedules():
    plan = cloud_tou.import_plan(cloud_tou.schedule(detail()), power_pct=80)
    ents = plan["entries"]
    charge = [e for e in ents if e["action"]["direction"] == "charge"]
    # 02:00-05:00 on Summer weekdays and every Winter day: two schedules, since one
    # with both months and both day sets would also charge on Summer weekends
    assert [(e["days"], e["months"]) for e in charge] == [
        ([0, 1, 2, 3, 4], [1, 2, 3, 10, 11, 12]), ([], [4, 5, 6, 7, 8, 9])]
    assert charge[0]["fire_at"] == "02:00" and charge[0]["duration_min"] == 180
    assert charge[0]["action"] == {"kind": "force", "direction": "charge", "power": 80, "unit": "pct"}
    assert charge[0]["enabled"] is False and charge[0]["trigger_type"] == "daily"
    assert charge[0]["name"] == "TOU charge 02:00-05:00 (Summer, Weekdays)"
    export = [e for e in ents if e["action"]["direction"] == "discharge"][0]
    assert export["fire_at"] == "21:00" and export["duration_min"] == 180      # to midnight
    assert export["days"] == [0, 1, 2, 3, 4] and export["months"] == [1, 2, 3, 10, 11, 12]
    # Self-consumption and aPower to home are the bridge's base mode: nothing to schedule
    assert {b["dispatch_id"] for b in plan["base"]} == {1, 6}


def test_solar_only_charging_has_no_bridge_action_and_is_listed():
    plan = cloud_tou.import_plan(cloud_tou.schedule(detail([blk("00:00", "10:00", 6),
                                                            blk("10:00", "14:00", 3),
                                                            blk("14:00", "24:00", 6)])))
    assert [e["months"] for e in plan["entries"]] == [[4, 5, 6, 7, 8, 9]]    # Winter's charge only
    assert plan["left_out"][0]["dispatch_id"] == 3 and plan["left_out"][0]["start"] == "10:00"


# ── the API ──────────────────────────────────────────────────────────────────
@pytest.fixture
def api(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from franklinwh_direct_connect_bridge import app as app_module, client as client_module, \
        config, db, mockgw, state, supervisor
    state.reset_gateways()
    store = MetricsStore(str(tmp_path / "m.db"))
    monkeypatch.setattr(db, "get_store", lambda *a, **k: store)

    async def _noop(*a, **k):
        return None
    monkeypatch.setattr(supervisor, "start_poller", _noop)
    monkeypatch.setattr(supervisor, "stop_poller", _noop)
    monkeypatch.setattr(supervisor, "is_running", lambda gid: True)
    monkeypatch.setattr(mockgw, "stop_mock", lambda gid: None)
    monkeypatch.setattr(client_module, "writes_enabled", lambda s: True)
    s = config.get_settings()
    monkeypatch.setattr(s, "fwh_cloud_email", "owner@example.invalid")
    monkeypatch.setattr(s, "fwh_cloud_password", "x")
    monkeypatch.setattr(s, "fwh_cloud_gateway", "")
    reads = []
    monkeypatch.setattr(cloud_tou, "read", lambda settings, serial: reads.append(serial) or detail())
    c = TestClient(app_module.create_app())
    gw = state.register_gateway("gw1", "192.0.2.10", "Home", serial="10060006A02F00000001")
    yield c, gw, reads
    state.reset_gateways()
    store.close()


def test_api_syncs_and_shows_the_copy_today_and_the_clashes(api):
    c, gw, reads = api
    v = c.get("/api/cloud/tou/schedule?gateway=gw1").json()
    assert v["available"] and v["latest"] is None and reads == []      # GET never calls the cloud
    gw.last_state = {"mode": "Time-of-Use"}
    c.post("/api/schedules", json={"name": "charge-cheap", "gateway_id": "gw1", "fire_at": "03:00",
                                   "duration_min": 60, "action": {"kind": "set_mode", "mode": "self"}})
    v = c.post("/api/cloud/tou/schedule/sync?gateway=gw1").json()
    assert reads == ["10060006A02F00000001"]                            # the gateway's own serial
    assert v["tou_active"] and v["latest"]["schedule"]["name"] == "EA116 TOU"
    assert v["latest"]["reason"] == "manual" and len(v["history"]) == 1
    assert v["today"] and isinstance(v["conflicts"], list)


def test_api_refuses_a_gateway_the_cloud_account_is_not_for(api, monkeypatch):
    from franklinwh_direct_connect_bridge import config
    c, _gw, reads = api
    monkeypatch.setattr(config.get_settings(), "fwh_cloud_gateway", "10060006A02F00000002")
    r = c.post("/api/cloud/tou/schedule/sync?gateway=gw1")
    assert r.status_code == 409 and "different gateway" in r.json()["detail"] and reads == []


def test_api_import_creates_the_schedules_disabled(api):
    c, _gw, _reads = api
    assert c.get("/api/cloud/tou/schedule/import?gateway=gw1").status_code == 404
    c.post("/api/cloud/tou/schedule/sync?gateway=gw1")
    plan = c.get("/api/cloud/tou/schedule/import?gateway=gw1&power_pct=60").json()
    r = c.post("/api/cloud/tou/schedule/import?gateway=gw1", json={"power_pct": 60})
    assert r.status_code == 201, r.json()
    assert len(r.json()["created"]) == len(plan["entries"]) == 3
    made = [s for s in c.get("/api/schedules").json()["schedules"] if s["name"].startswith("TOU ")]
    assert len(made) == 3 and not any(s["enabled"] for s in made)
    assert all(s["gateway_id"] == "gw1" for s in made)


# ── the page ─────────────────────────────────────────────────────────────────
def test_the_scheduler_has_the_tou_view_and_asks_before_importing():
    import pathlib
    pkg = pathlib.Path(__file__).resolve().parents[1] / "src" / "franklinwh_direct_connect_bridge"
    html = (pkg / "templates" / "tabs" / "scheduler.html").read_text()
    js = (pkg / "static" / "js" / "scheduler_tab.js").read_text()
    assert "['tou','FranklinWH TOU']" in html and "if (v === 'tou') await this.loadTou();" in js
    for tid in ("tou-sync", "tou-advice", "tou-conflicts", "tou-history", "tou-import-open",
                "tou-import-power", "tou-import-apply"):
        assert f'data-testid="{tid}"' in html, tid
    dlg = html[html.index('data-testid="tou-import"'):]
    assert "dialog_msg('touImp.msg')" in dlg and "disabled" in dlg     # result in the dialog
    assert "it runs on the aGate without the bridge" in dlg               # the trade-off, asked first


def test_the_clashes_are_a_table_in_columns():
    import pathlib
    html = (pathlib.Path(__file__).resolve().parents[1] / "src" / "franklinwh_direct_connect_bridge"
            / "templates" / "tabs" / "scheduler.html").read_text()
    t = html[html.index('data-testid="tou-conflicts-table"'):]
    t = t[:t.index("</table>")]
    for col in ("Schedule", "Time", "Repeats", "TOU block", "Bridge"):
        assert f">{col}</th>" in t, col
    assert "editById(c.schedule_id)" in t
