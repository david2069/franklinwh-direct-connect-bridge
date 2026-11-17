"""TOU schedule rates and the Home Assistant TOU entities (#656 phase 1, #421).

The copy keeps the buy and sell rates (``eletic*``), one set per day type, so a band can
cost one thing on weekdays and another at weekends (owner 2026-11-18: a band per day type).
The unit is a guess: please confirm against the FranklinWH app. The schedule is re-read
once a day as well as at start-up, when TOU mode is set and on Sync now. HA gets TOU
Schedule, Dispatch Now/Next and Tariff Now/Next, worked out from the copy (no cloud read),
with source ``cloud`` (#711)."""
import datetime as dt
import pathlib

from franklinwh_direct_connect_bridge import cloud_tou
from franklinwh_direct_connect_bridge.publish import entities

from test_cloud_tou import api, blk  # noqa: F401  (the TOU API fixture)

PKG = pathlib.Path(__file__).resolve().parents[1] / "src" / "franklinwh_direct_connect_bridge"
TZ = dt.timezone(dt.timedelta(hours=11))


def day(name, day_type, blocks, **rates):
    return {"dayName": name, "dayType": day_type, "detailVoList": blocks,
            "eleticRatePeak": None, "eleticRateShoulder": None, "eleticRateValley": None,
            "eleticRateSharp": None, "eleticRateSuperOffPeak": None,
            "eleticRateGridFee": None, "eleticSellPeak": None, "eleticSellShoulder": None,
            "eleticSellValley": None, "eleticSellSharp": None,
            "eleticSellSuperOffPeak": None, **rates}


def detail():
    wd = [blk("00:00", "02:00", 6, 0), blk("02:00", "05:00", 8, 4),
          blk("05:00", "15:00", 6, 1), blk("15:00", "21:00", 1, 2),
          blk("21:00", "24:00", 7, 2)]
    return {
        "template": {"name": "EA116 TOU", "electricCompany": "Amber Electric",
                     "updateTime": "2026-03-19 13:44:38"},
        "strategyList": [
            {"seasonName": "Summer", "month": "10,11,12,1,2,3",
             "dayTypeVoList": [
                 day("Weekdays", 1, wd, eleticRateValley=0.2, eleticRateSuperOffPeak=0.1,
                     eleticRateShoulder=0.3, eleticRatePeak=0.5, eleticSellPeak=0.12,
                     eleticSellShoulder=0.05),
                 day("Weekends,Holidays", 2, [blk("00:00", "24:00", 6, 0)],
                     eleticRateValley=0.18, eleticSellValley=0.04)]},
            {"seasonName": "Winter", "month": "4,5,6,7,8,9",
             "dayTypeVoList": [day("Everyday", 3, [blk("00:00", "24:00", 6, 1)],
                                   eleticRateShoulder=0.25, eleticRateSharp=0.9,
                                   eleticRateGridFee=1.1)]},
        ],
    }


# ── rates in the copy ────────────────────────────────────────────────────────
def test_the_copy_keeps_buy_and_sell_rates_per_day_type():
    s = cloud_tou.schedule(detail())
    wd, we = s["seasons"][0]["days"]
    assert wd["rates"]["On-peak"] == {"buy": 0.5, "sell": 0.12}
    assert wd["rates"]["Mid-peak"] == {"buy": 0.3, "sell": 0.05}
    assert wd["rates"]["Off-peak"] == {"buy": 0.2, "sell": None}
    assert wd["rates"]["Super off-peak"] == {"buy": 0.1, "sell": None}
    # the same band at weekends has its own rate (a band per day type)
    assert we["rates"] == {"Off-peak": {"buy": 0.18, "sell": 0.04}}
    winter = s["seasons"][1]["days"][0]
    assert winter["rates"]["Mid-peak"] == {"buy": 0.25, "sell": None}
    assert winter["rates"]["Sharp"] == {"buy": 0.9, "sell": None}
    assert winter["grid_fee"] == 1.1
    assert "please confirm" in s["rate_unit"]


def test_todays_blocks_carry_their_rates_and_the_blocks_are_unchanged():
    s = cloud_tou.schedule(detail())
    mon = dt.date(2026, 11, 16)
    plain = cloud_tou.blocks_on(s, mon)
    assert "buy" not in plain[0]                    # the schedule's blocks as before
    today = cloud_tou.blocks_with_rates(s, mon)
    assert [(b["start"], b["buy"], b["sell"]) for b in today] == [
        ("00:00", 0.2, None), ("02:00", 0.1, None), ("05:00", 0.3, 0.05),
        ("15:00", 0.5, 0.12), ("21:00", 0.5, 0.12)]
    sat = cloud_tou.blocks_with_rates(s, dt.date(2026, 11, 21))
    assert sat[0]["buy"] == 0.18 and sat[0]["sell"] == 0.04


def test_the_api_shows_todays_rates(api, monkeypatch):
    c, _gw, _reads = api
    monkeypatch.setattr(cloud_tou, "read", lambda settings, serial: detail())
    v = c.post("/api/cloud/tou/schedule/sync?gateway=gw1").json()
    assert v["today"] and all("buy" in b and "sell" in b for b in v["today"])
    assert "please confirm" in v["latest"]["schedule"]["rate_unit"]


def test_the_view_shows_the_rates_and_the_unit_guess():
    html = (PKG / "templates" / "tabs" / "scheduler.html").read_text()
    assert 'data-testid="tou-rates"' in html and 'data-testid="tou-rate-unit"' in html
    assert "b.buy" in html and "b.sell" in html


# ── daily re-read ────────────────────────────────────────────────────────────
def test_the_schedule_is_re_read_once_a_day():
    now = 1_000_000.0
    assert cloud_tou.sync_reason("Self-Consumption", "Self-Consumption", True,
                                 last_try=now - 86_400, now=now) == "daily"
    assert cloud_tou.sync_reason("Self-Consumption", "Self-Consumption", True,
                                 last_try=now - 3_600, now=now) is None
    # the existing reasons still win
    assert cloud_tou.sync_reason("Time-of-Use", "Self-Consumption", True,
                                 last_try=now - 86_400, now=now) == "tou-mode"
    assert cloud_tou.sync_reason("", "", False, last_try=None, now=now) == "start"
    src = (PKG / "app.py").read_text()
    assert "last_try=_tou_last_try" in src


# ── Home Assistant ───────────────────────────────────────────────────────────
TOU_KEYS = ("tou_schedule", "tou_dispatch_now", "tou_dispatch_next", "tou_tariff_now",
            "tou_tariff_next")


def test_the_tou_entities_are_cloud_sourced_on_their_own_topic():
    by = {e["key"]: e for e in entities.ENTITIES}
    for k in TOU_KEYS:
        assert by[k]["source"] == "cloud" and by[k]["topic"] == "tou", k
        assert k in entities.OWN_TOPIC_KEYS
    names = {by[k]["name"] for k in TOU_KEYS}
    assert names == {"TOU Schedule", "TOU Dispatch Now", "TOU Dispatch Next",
                     "TOU Tariff Now", "TOU Tariff Next"}
    skip = entities.source_skip(cloud=False, modbus=True)
    assert set(TOU_KEYS) <= skip
    assert not set(TOU_KEYS) & entities.source_skip(cloud=True, modbus=True)
    cfgs, _, _ = entities.discovery_configs("n", {}, "fwh", "homeassistant")
    topics = {c["unique_id"]: c["state_topic"] for _, c in cfgs}
    assert topics["franklinwh_n_tou_tariff_now"] == "fwh/n/tou"


def test_the_ha_payload_is_worked_out_from_the_copy():
    s = cloud_tou.schedule(detail())
    copy = {"schedule": s, "checked_ts": 1_763_000_000.0}
    now = dt.datetime(2026, 11, 16, 16, 30, tzinfo=TZ)     # Monday, in the 15:00 block
    p = cloud_tou.ha_payload(copy, now)
    assert p["schedule"] == "EA116 TOU" and p["utility"] == "Amber Electric"
    assert p["cloud_updated"] == "2026-03-19 13:44:38"
    assert len(p["today"]) == 5 and p["today"][3]["buy"] == 0.5
    assert p["dispatch_now"] == "aPower to home"
    assert p["dispatch_now_start"] == "2026-11-16T15:00:00+11:00"
    assert p["dispatch_now_end"] == "2026-11-16T21:00:00+11:00"
    assert p["dispatch_next"] == "aPower to home/grid"
    assert p["dispatch_next_start"] == "2026-11-16T21:00:00+11:00"
    assert p["tariff_now"] == "On-peak" and p["tariff_now_buy"] == 0.5
    assert p["tariff_now_sell"] == 0.12
    # the next band change: on-peak runs to midnight, then Tuesday's off-peak
    assert p["tariff_next"] == "Off-peak" and p["tariff_next_buy"] == 0.2
    assert p["tariff_next_start"] == "2026-11-17T00:00:00+11:00"
    assert "please confirm" in p["rate_unit"]
    assert cloud_tou.ha_payload(None, now) is None


def test_the_poller_publishes_tou_without_a_cloud_read():
    src = (PKG / "poller.py").read_text()
    assert "cloud_tou.ha_payload(" in src and "publish_tou(" in src
    assert "cloud_tou.sync(" not in src and "cloud_tou.read(" not in src
