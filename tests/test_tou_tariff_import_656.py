"""Import the FranklinWH TOU schedule as a tariff plan (#656 phase 2, owner 2026-11-18).

Billing → Plans & meters → Import from FranklinWH, shown while the cloud is signed in for
the meter's gateway. Pre-fill from the latest dated copy (utility, tariff, country from the
cloud; seasons, bands, blocks and buy/sell from the copy, a band per day type), with the
guesses marked please confirm; ask for what the cloud doesn't hold (each "doesn't apply");
Check with the tariff check and today's price by hour; Import as a plan of the meter. A
newer copy that differs says "Schedule changed — re-import?" on the plan. Nothing is
written to the cloud or the aGate; no catalogues."""
import datetime as dt
import pathlib

from franklinwh_direct_connect_bridge import cloud_tou, rate_model, tariff_io

from test_cloud_tou import api, blk  # noqa: F401  (the TOU API fixture)
from test_cloud_tou_rates_656 import detail

PKG = pathlib.Path(__file__).resolve().parents[1] / "src" / "franklinwh_direct_connect_bridge"


def copy(**tpl):
    d = detail()
    d["template"].update(tpl)
    return {"id": 7, "first_ts": 1000.0, "checked_ts": 1000.0,
            "cloud_updated": d["template"]["updateTime"], "schedule": cloud_tou.schedule(d)}


SITE = {"id": "s1", "timezone": "Australia/Sydney", "currency": "", "region": "AU-NSW"}


# ── pre-fill ─────────────────────────────────────────────────────────────────
def test_prefill_takes_utility_tariff_and_country_from_the_cloud_and_marks_the_guesses():
    p = cloud_tou.prefill(copy(name="Ausgrid EA116 TOU", countryEn="Australia",
                               provinceEn="New South Wales"), SITE, today=dt.date(2026, 11, 18))
    assert p["tariff_name"] == "Ausgrid EA116 TOU" and p["retailer"] == "Amber Electric"
    assert p["country"] == "AU" and p["region"] == "New South Wales"
    assert p["network"] == "Ausgrid"                       # found in the tariff's name
    assert p["currency"] == "AUD" and p["unit"] == "dollars"
    assert p["effective_start"] == "2026-11-18" and p["timezone"] == "Australia/Sydney"
    assert p["copy_id"] == 7
    for k in ("currency", "unit", "network", "effective_start", "day_types"):
        assert k in p["confirm"], k
    # the seasons as the app has them, a band per day type
    summer = p["seasons"][0]
    assert summer["name"] == "Summer" and [d["name"] for d in summer["days"]] == [
        "Weekdays", "Weekends,Holidays"]
    assert summer["days"][1]["rates"]["Off-peak"] == {"buy": 0.18, "sell": 0.04}


def test_prefill_without_a_country_uses_the_sites_region_and_lists_what_it_leaves_out():
    p = cloud_tou.prefill(copy(), SITE, today=dt.date(2026, 11, 18))
    assert p["country"] == "AU" and p["network"] == ""
    # Off-peak costs 0.2 on weekdays and 0.18 at weekends in Summer: one rate per band in
    # a season, so the user picks; the pre-pick is the day type with most hours in it
    sp = next(s for s in p["split"] if s["season"] == "Summer" and s["band"] == "Off-peak")
    assert [c["day"] for c in sp["choices"]] == ["Weekdays", "Weekends,Holidays"]
    assert sp["pick"] == "Weekends,Holidays"               # 48 h a weekend v 10 h a week
    # Sharp has no band the bridge prices, and the grid fee's meaning is unknown: shown
    assert {"season": "Winter", "day": "Everyday", "band": "Sharp", "buy": 0.9,
            "sell": None} in p["left_out"]
    assert p["grid_fee"] == [{"season": "Winter", "day": "Everyday", "value": 1.1}]


# ── the tariff-profile ───────────────────────────────────────────────────────
ANSWERS = {"unit": "dollars", "network": "Ausgrid", "billing_day": 15, "supply": 1.2,
           "tax_pct": 10, "demand": {"start": "16:00", "end": "21:00", "rate": 0.4},
           "bonus": None, "export_charge": None, "other": None,
           "effective_start": "2026-11-18", "effective_end": None,
           "picks": {"Summer|Off-peak": "Weekdays"}}


def test_to_profile_prices_the_copy_through_the_same_rate_model_as_billing():
    p = cloud_tou.prefill(copy(countryEn="Australia"), SITE, today=dt.date(2026, 11, 18))
    bundle = cloud_tou.to_profile(copy(countryEn="Australia"), {**p, **ANSWERS}, "gw1")
    assert bundle["type"] == tariff_io.PROFILE_TYPE
    prof = bundle["profile"]
    assert prof["name"] == "EA116 TOU" and prof["retailer"] == "Amber Electric"
    assert prof["network"] == "Ausgrid" and prof["country"] == "AU" and prof["plan_type"] == "tou"
    assert prof["timezone"] == "Australia/Sydney" and prof["effective_start"] == "2026-11-18"
    util, tar, _tz = tariff_io.to_local(prof)
    seasons = tar["pricing"]["seasons"]
    assert not rate_model.validate(seasons, None)
    mon, sat = dt.datetime(2026, 11, 16), dt.datetime(2026, 11, 21)
    assert rate_model.resolve(seasons, mon.replace(hour=16), 0)["buy"] == 0.5     # On-peak
    assert rate_model.resolve(seasons, mon.replace(hour=16), 0)["sell"] == 0.12
    assert rate_model.resolve(seasons, mon.replace(hour=3), 0)["buy"] == 0.1      # Super off
    # the picked rate for the split band, at weekends too
    assert rate_model.resolve(seasons, mon.replace(hour=1), 0)["buy"] == 0.2
    assert rate_model.resolve(seasons, sat.replace(hour=12), 0)["buy"] == 0.2
    assert rate_model.resolve(seasons, dt.datetime(2026, 6, 1, 12), 0)["buy"] == 0.25
    # what the cloud lacks, from the answers
    assert tar["billing_cycle_day"] == 15
    assert tar["fixed_charges"] == [{"type": "supply", "description": "Daily supply charge",
                                     "levied_by": "utility", "frequency": "daily",
                                     "rate": 1.2, "tax_rate": 0.1}]
    assert tar["demand_window"]["start"] == "16:00" and tar["pricing"]["demand_rate"] == 0.4
    assert tar["bonus_window"] is None and tar["charge_window"] is None
    # where it came from, for the re-import notice
    assert tar["pricing"]["source"] == {"kind": "franklinwh_tou", "gateway_id": "gw1",
                                        "copy_id": 7}


def test_cents_are_divided_and_doesnt_apply_leaves_a_charge_out():
    p = cloud_tou.prefill(copy(), SITE, today=dt.date(2026, 11, 18))
    a = {**p, **ANSWERS, "unit": "cents", "billing_day": None, "supply": None,
         "tax_pct": None, "demand": None,
         "bonus": {"start": "17:00", "end": "20:00", "rate": 0.1},
         "export_charge": {"start": "10:00", "end": "15:00", "rate": 0.02, "free_kwh": 5}}
    _u, tar, _tz = tariff_io.to_local(cloud_tou.to_profile(copy(), a, "gw1")["profile"])
    on = rate_model.resolve(tar["pricing"]["seasons"], dt.datetime(2026, 11, 16, 16), 0)
    assert on["buy"] == 0.005 and on["sell"] == 0.0012
    assert tar["billing_cycle_day"] == 1 and not tar["fixed_charges"]
    assert tar["demand_window"] is None
    assert tar["bonus_window"]["start"] == "17:00" and tar["pricing"]["export_bonus_rate"] == 0.1
    assert tar["charge_window"]["start"] == "10:00"
    assert tar["pricing"]["export_charge_rate"] == 0.02
    assert tar["pricing"]["export_charge_free_kwh_per_day"] == 5


def test_reimport_is_offered_when_a_newer_copy_differs():
    t = {"id": "tar_1", "pricing": {"source": {"kind": "franklinwh_tou", "gateway_id": "gw1",
                                               "copy_id": 7}}}
    assert cloud_tou.reimport_needed(t, {"gw1": 7}) is None
    assert cloud_tou.reimport_needed(t, {"gw1": 9}) == {"gateway_id": "gw1", "copy_id": 9}
    assert cloud_tou.reimport_needed({"id": "x", "pricing": {}}, {"gw1": 9}) is None


# ── the API ──────────────────────────────────────────────────────────────────
def _site_meter(c, reads, monkeypatch):
    """A site and meter; the cloud's schedule with its rates (no login: ``read`` is
    stubbed)."""
    from franklinwh_direct_connect_bridge import db
    monkeypatch.setattr(cloud_tou, "read", lambda settings, serial: reads.append(serial) or detail())
    st = db.get_store(None)
    st.create_site(sid="s1", name="Home", timezone="Australia/Sydney", region="AU-NSW",
                   is_default=True)
    st.create_meter(mid="m1", site_id="s1", is_default=True)
    return st


def test_api_prefills_checks_and_imports_a_plan_without_writing_to_the_cloud(api, monkeypatch):
    c, _gw, reads = api
    st = _site_meter(c, reads, monkeypatch)
    s = c.get("/api/cloud/tou/tariff/status").json()
    assert [g["id"] for g in s["gateways"]] == ["gw1"]
    p = c.get("/api/cloud/tou/tariff?gateway=gw1&meter=m1").json()
    assert reads == ["10060006A02F00000001"]               # no copy yet: Sync now once
    assert p["tariff_name"] == "EA116 TOU" and p["meter_id"] == "m1"
    body = {"gateway": "gw1", "meter_id": "m1", "answers": {**p, **ANSWERS}}
    chk = c.post("/api/cloud/tou/tariff/check", json=body).json()
    assert chk["problems"] == [] and len(chk["hours"]) == 24
    assert chk["preview"]["tariff_name"] == "EA116 TOU" and chk["preview"]["meter_id"] == "m1"
    assert all(set(h) >= {"hour", "band", "buy", "sell"} for h in chk["hours"])
    r = c.post("/api/cloud/tou/tariff/import", json=body).json()
    assert r["ok"] and r["attached_meter"] == "m1"
    t = st.tariff(r["tariff_id"])
    assert t["name"] == "EA116 TOU" and t["pricing"]["source"]["copy_id"] == p["copy_id"]
    assert reads == ["10060006A02F00000001"]               # Check and Import read nothing
    assert c.get("/api/cloud/tou/tariff/status").json()["reimport"] == {}


def test_api_says_a_changed_schedule_needs_reimport(api, monkeypatch):
    c, _gw, reads = api
    _site_meter(c, reads, monkeypatch)
    p = c.get("/api/cloud/tou/tariff?gateway=gw1&meter=m1").json()
    r = c.post("/api/cloud/tou/tariff/import",
               json={"gateway": "gw1", "meter_id": "m1", "answers": {**p, **ANSWERS}}).json()
    changed = detail()
    changed["template"]["updateTime"] = "2026-11-18 09:00:00"
    monkeypatch.setattr(cloud_tou, "read", lambda settings, serial: changed)
    c.post("/api/cloud/tou/schedule/sync?gateway=gw1")
    s = c.get("/api/cloud/tou/tariff/status").json()
    assert s["reimport"][r["tariff_id"]]["gateway_id"] == "gw1"


def test_api_is_refused_without_the_cloud(api, monkeypatch):
    from franklinwh_direct_connect_bridge import config
    c, _gw, reads = api
    monkeypatch.setattr(config.get_settings(), "fwh_cloud_password", "")
    assert c.get("/api/cloud/tou/tariff/status").json()["gateways"] == []
    r = c.get("/api/cloud/tou/tariff?gateway=gw1")
    assert r.status_code == 409 and reads == []


def test_the_page_has_the_steps_in_the_plans_dialog_and_the_notice():
    part = (PKG / "templates" / "partials" / "plans_meters.html").read_text()
    for tid in ("meter-plan-import-fwh", "tou-tariff-dialog", "tou-tariff-step-prefill",
                "tou-tariff-step-ask", "tou-tariff-step-check", "tou-tariff-done",
                "meter-plan-reimport"):
        assert f'data-testid="{tid}"' in part, tid
    assert "Schedule changed — re-import?" in part
    assert "doesn't apply" in part and "please confirm" in part
    js = (PKG / "static" / "js" / "settings_tab.js").read_text()
    assert "api/cloud/tou/tariff" in js
