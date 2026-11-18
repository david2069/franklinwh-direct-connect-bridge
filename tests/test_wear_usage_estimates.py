"""Battery warranty & wear: usage against the allowance (owner 2026-11-18).

The card showed "pace" (remaining ÷ days left) but not the battery's actual use, and left the
install date and throughput used blank. The owner observed on their aGate that the FranklinWH
cloud's energy reports start at the manufacturing date with zeros and real data starts on the
commissioning date, so the first day with data estimates the install date (please confirm;
seen on one site only). Used is the cloud's discharge total since then, beside the warranty's
own "warranted − remaining"; the actual kWh a day is compared with the allowance; SoH with the
guaranteed end SoH; and each unit's warranty end is listed with its serial masked."""
import datetime as dt
import pathlib

import pytest

from franklinwh_direct_connect_bridge import providers, state, wear
from franklinwh_direct_connect_bridge.db import MetricsStore

PKG = pathlib.Path(__file__).resolve().parents[1] / "src" / "franklinwh_direct_connect_bridge"
NOW = dt.datetime(2026, 11, 18, 12).timestamp()

CLOUD = {"expirationTime": "2036-07-22", "throughput": 43, "remainThroughput": 34903.64,
         "deviceExpirationList": [
             {"sn": "10060006A02F24170091", "model": "aGate X-01-AU", "type": 1,
              "expirationTime": "2036-07-22"},
             {"sn": "APWR0000000000001234", "model": "aPower X-01-AU", "type": 2,
              "expirationTime": "2036-07-22", "subModuleExpirationTime": "2031-07-22"}]}


def payload(labels, discharge, home=None):
    home = home if home is not None else discharge
    return {"labels": labels, "series": [
        {"key": "home", "values": home},
        {"key": "battery_discharge", "values": discharge},
        {"key": "battery_charge", "values": [None if v is None else -v for v in discharge]}]}


def months(year, first):
    return [0.0 if m < first else 100.0 for m in range(1, 13)]


HISTORY = {
    ("lifetime", None): payload(["2023", "2024", "2025", "2026"], [0.0, 2600.0, 3300.0, 2900.0]),
    ("year", "2024"): payload([f"2024-{m:02d}" for m in range(1, 13)], months(2024, 3)),
    ("month", "2024-03"): payload([f"2024-03-{d:02d}" for d in range(1, 32)],
                                  [0.0 if d < 12 else 9.0 for d in range(1, 32)]),
}


def read(period, on):
    key = (period, None if period == "lifetime" else
           (str(on.year) if period == "year" else f"{on.year}-{on.month:02d}"))
    return HISTORY[key]


@pytest.fixture
def st(tmp_path):
    s = MetricsStore(str(tmp_path / "m.db"))
    yield s
    s.close()


@pytest.fixture
def signed_in(monkeypatch):
    monkeypatch.setattr(providers, "cloud_auth_status", lambda: {"state": "valid"})


def test_the_first_day_with_data_is_found_from_lifetime_to_year_to_month():
    assert wear.first_day_with_data(read) == "2024-03-12"
    # no data at all: nothing to estimate
    assert wear.first_day_with_data(lambda p, on: payload(["2025", "2026"], [0.0, None])) is None


def test_history_is_read_once_a_day_only_when_signed_in(st, monkeypatch, signed_in):
    calls = []

    def counting(period, on):
        calls.append(period)
        return read(period, on)
    h = wear.history(st, None, "gw1", "SERIAL", NOW, read=counting, since=lambda: "2024-03-14")
    assert h["first_day"] == "2024-03-12" and h["activated"] == "2024-03-14"
    assert h["discharged_kwh"] == pytest.approx(8800.0)
    n = len(calls)
    wear.history(st, None, "gw1", "SERIAL", NOW + 3600, read=counting, since=lambda: None)
    assert len(calls) == n                                   # once a day
    # the next day: the commissioning day is kept; only the lifetime total is read again
    wear.history(st, None, "gw1", "SERIAL", NOW + 86400, read=counting, since=lambda: None)
    assert calls[n:] == ["lifetime"]
    monkeypatch.setattr(providers, "cloud_auth_status", lambda: {"state": "unconfigured"})
    st2 = MetricsStore(str(pathlib.Path(st.path).with_name("n.db")))
    try:
        assert wear.history(st2, None, "gw1", "SERIAL", NOW, read=counting) is None
    finally:
        st2.close()


def _report(st, monkeypatch, hist=True, **values):
    monkeypatch.setattr(state, "get_gateway", lambda gid: type("G", (), {
        "serial": "SERIAL", "apower_soh": {"1": 94.7}})())
    if values:
        wear.save(st, "gw1", values)
    h = ({"first_day": "2024-03-12", "activated": "2024-03-14", "discharged_kwh": 8800.0}
         if hist else None)
    return wear.report(st, None, "gw1", NOW, cloud_fn=lambda *a: wear.cloud_subset(CLOUD),
                       history_fn=lambda *a: h)


def test_install_date_is_prefilled_from_the_first_day_with_data_as_an_estimate(st, monkeypatch):
    f = _report(st, monkeypatch)["fields"]["install_date"]
    assert f["value"] == "2024-03-12" and f["source"] == "cloud_history"
    assert f["confirm"] is True and f["estimated"] is True
    assert "estimated: first day with data in the FranklinWH cloud (observed on one site)" in f["note"]
    assert "2024-03-14" in f["note"]                         # the activation date, cross-checked
    # a value the user entered always wins
    f = _report(st, monkeypatch, install_date="2024-04-01")["fields"]["install_date"]
    assert f == {"value": "2024-04-01", "source": "user", "confirm": False}


def test_used_shows_each_source_and_marks_the_cloud_history_one_estimated(st, monkeypatch):
    r = _report(st, monkeypatch)
    by = {u["source"]: u for u in r["used_sources"]}
    assert by["warranty"]["kwh"] == pytest.approx(8096.36, abs=0.01)   # 43 MWh − 34,904 kWh
    assert by["warranty"]["estimated"] is False
    assert by["cloud_history"]["kwh"] == pytest.approx(8800.0)
    assert by["cloud_history"]["estimated"] is True
    assert "used_kwh" in r and "pace" in r                   # the existing figures stay


def test_actual_use_is_compared_with_the_allowance_in_plain_words(st, monkeypatch):
    r = _report(st, monkeypatch)
    pc = r["pace_compare"]
    days = (dt.date(2026, 11, 18) - dt.date(2024, 3, 12)).days
    assert pc["actual_kwh_per_day"] == pytest.approx(8096.36 / days, abs=0.01)
    assert pc["allowance_kwh_per_day"] == pytest.approx(r["pace"]["daily_kwh"])
    assert pc["estimated"] is True                           # the install date is an estimate
    assert pc["text"].startswith(f"using {8096.36 / days:.1f} kWh a day")
    assert f"allowance {r['pace']['daily_kwh']:.1f} kWh a day" in pc["text"]


def test_soh_is_compared_with_the_guaranteed_end_soh_when_set(st, monkeypatch):
    sc = _report(st, monkeypatch)["soh_compare"]
    assert sc["end_soh_pct"] is None and sc["text"] == "Enter the warranty's end SoH to compare."
    sc = _report(st, monkeypatch, end_soh_pct=70)["soh_compare"]
    assert sc["margin_pts"] == pytest.approx(24.7)
    assert sc["text"] == "94.7% now; guaranteed 70% at the end of the warranty (24.7 points above)."


def test_each_units_warranty_end_is_listed_with_its_serial_masked(st, monkeypatch):
    devs = _report(st, monkeypatch)["devices"]
    assert devs == [
        {"model": "aGate X-01-AU", "serial": "…0091", "expiry": "2036-07-22", "sub_module_expiry": None},
        {"model": "aPower X-01-AU", "serial": "…1234", "expiry": "2036-07-22",
         "sub_module_expiry": "2031-07-22"}]
    import json
    assert "24170091" not in json.dumps(_report(st, monkeypatch))


def test_without_the_cloud_history_nothing_is_guessed(st, monkeypatch):
    r = _report(st, monkeypatch, hist=False)
    assert r["fields"]["install_date"]["value"] is None
    assert "cloud_history" not in {u["source"] for u in r["used_sources"]}
    assert r["pace_compare"] is None                         # no install date: no daily use


def test_the_card_shows_the_comparisons_and_says_what_is_estimated():
    html = (PKG / "templates" / "tabs" / "settings.html").read_text()
    for tid in ("wear-used-sources", "wear-pace-compare", "wear-soh-compare", "wear-devices"):
        assert f'data-testid="{tid}"' in html, tid
    # an estimated field says so under its input, with the note from the report
    assert ":data-testid=\"'wear-estimated-' + k\"" in html and "wear.fields[k].note" in html
