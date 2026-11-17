"""Scheduler → FranklinWH TOU: clashes on a timeline (owner 2026-11-18: "the Clashes section
looks dumb n excessive including the silly title. Tone it down" and "visual time
representation of conflicts"). Under today's TOU bar, a second bar on the same 24 h scale
shows this bridge's mode and Force schedules, with the clashing minutes marked on both;
the heading is a plain "Clashes today". What counts as a clash is unchanged (#421)."""
import pathlib

from franklinwh_direct_connect_bridge import cloud_tou

from test_cloud_tou import MON, api, detail, entry  # noqa: F401  (fixture)

PKG = pathlib.Path(__file__).resolve().parents[1] / "src" / "franklinwh_direct_connect_bridge"


def _html():
    return (PKG / "templates" / "tabs" / "scheduler.html").read_text()


ENTRIES = [entry("charge-cheap", "force", "03:00", 60),                       # 8 + charge: ok
           entry("charge-peak", "force", "16:00", 60),                         # 1 + charge: clash
           entry("storm", "set_mode", "19:00", 120),                           # a mode: never
           entry("porch-light", "smart_circuit", "18:00", 60),                 # not on the bar
           entry("off", "force", "10:00", 60, enabled=False)]


def test_todays_bridge_spans_are_the_mode_and_force_schedules():
    s = cloud_tou.schedule(detail())
    bars = cloud_tou.bridge_today(s, ENTRIES, MON, "gw1")
    assert [(b["schedule_id"], b["start"], b["end"], b["kind"]) for b in bars["spans"]] == [
        ("charge-cheap", "03:00", "04:00", "force"),
        ("charge-peak", "16:00", "17:00", "force"),
        ("storm", "19:00", "21:00", "set_mode")]
    assert [b["label"] for b in bars["spans"]] == ["Force charge", "Force charge", "Mode: Emergency Backup"]
    assert [b["clash"] for b in bars["spans"]] == [False, True, False]


def test_the_clash_marks_are_the_same_clashes_as_the_table():
    s = cloud_tou.schedule(detail())
    bars = cloud_tou.bridge_today(s, ENTRIES, MON, "gw1")
    rows = cloud_tou.conflicts(s, ENTRIES, MON, "gw1")
    assert [(m["start"], m["end"], m["schedule_id"]) for m in bars["clashes"]] == [
        (r["start"], r["end"], r["schedule_id"]) for r in rows] == [("16:00", "17:00", "charge-peak")]
    assert bars["clashes"][0]["start_min"] == 960 and bars["clashes"][0]["end_min"] == 1020


def test_a_repeating_force_marks_each_clashing_run_not_the_gaps():
    s = cloud_tou.schedule(detail())
    every15 = entry("storm-charge", "force", "00:00", 6, trigger_type="interval",
                    interval_min=15, anchor="00:00")
    bars = cloud_tou.bridge_today(s, [every15], MON, "gw1")
    marks = [(m["start_min"], m["end_min"]) for m in bars["clashes"]]
    assert (0, 6) in marks and (15, 21) in marks and not any(lo < 15 < hi for lo, hi in marks)
    assert not any(120 <= lo < 300 for lo, _ in marks)          # 02:00-05:00 grid charge: ok


def test_no_bridge_schedules_today_means_no_second_bar():
    s = cloud_tou.schedule(detail())
    assert cloud_tou.bridge_today(s, [], MON, "gw1") == {"spans": [], "clashes": []}


def test_the_api_gives_the_bars(api):  # noqa: F811
    c, gw, _reads = api
    gw.last_state = {"mode": "Time-of-Use"}
    r = c.post("/api/schedules", json={"name": "charge-peak", "gateway_id": "gw1", "fire_at": "16:00",
                                       "duration_min": 60, "action": {"kind": "force",
                                       "direction": "charge", "unit": "pct", "power": 50,
                                       "target_soc": 90}})
    assert r.status_code in (200, 201), r.json()
    v = c.post("/api/cloud/tou/schedule/sync?gateway=gw1").json()
    assert [b["name"] for b in v["bridge"]["spans"]] == ["charge-peak"]
    assert [(m["start"], m["end"]) for m in v["bridge"]["clashes"]] == [("16:00", "17:00")]
    assert v["conflicts"]                                          # the table is still there


def test_the_heading_is_toned_down():
    html = _html()
    block = html[html.index('data-testid="tou-conflicts"'):]
    block = block[:block.index('data-testid="tou-conflicts-table"')]
    assert "Clashes today" in block and "a Force that contradicts" not in block
    assert "uppercase" not in block
    assert "No clashes today." in block and ">None.<" not in block


def test_the_page_draws_the_bridge_bar_ticks_and_clash_marks():
    html = _html()
    for tid in ("tou-bridge-bar", "tou-bridge-span", "tou-clash-mark", "tou-bar-clash",
                "tou-ticks"):
        assert f'data-testid="{tid}"' in html, tid
    bar = html[html.index('data-testid="tou-bridge-bar"') - 300:]
    assert 'x-show="tou.bridge && tou.bridge.spans.length"' in bar[:600]  # none → no bar
    for h in ("0", "6", "12", "18", "24"):
        assert f"[0, 6, 12, 18, 24]" in html
    # tap shows the span's name and times, as well as hover
    assert "touSpanTip" in html and "touSpanTip" in (PKG / "static" / "js" / "scheduler_tab.js").read_text()
