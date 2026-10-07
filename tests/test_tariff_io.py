"""FEAT-IMPORT-AGL-SETUP — tariff-profile interchange with the Modbus bridge (both ways)."""
import datetime as dt

from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import tariff_io, rate_model
from franklinwh_direct_connect_bridge import app as app_module, config, environment, db
from franklinwh_direct_connect_bridge.db import MetricsStore

# A trimmed but faithful slice of the user's real "AGL Energy Ausgrid NSW" export.
AGL = {
    "type": "franklinwh-bridge/tariff-profile", "version": 1,
    "profile": {
        "name": "AGL Energy Ausgrid NSW", "retailer": "AGL", "network": "Ausgrid",
        "plan_type": "tou", "country": "AU", "timezone": "Australia/Sydney",
        "demand_window": {"months": [1, 2], "days": [], "start": "16:00", "end": "21:00"},
        "bonus_window": {"months": [], "days": [], "start": "17:00", "end": "21:00"},
        "pricing": {
            "billing_cycle_day": 1, "demand_rate": 0.3949, "demand_interval_min": 30,
            "demand_charge_basis": "per_kw_day", "export_bonus_rate": 0.28,
            "export_charge": {"window": {"months": [], "days": [], "start": "10:00", "end": "15:00"},
                              "rate": 0.013552, "free_kwh_per_day": 6.83},
            "fixed_charges": [{"type": "supply", "description": "AGL daily supply charge",
                               "levied_by": "utility", "frequency": "daily", "rate": 1.58631,
                               "tax_rate": 0}],
            "seasons": [{"id": "peak", "name": "Peak season", "months": [11, 12, 1, 2, 3, 6, 7, 8],
                         "blocks": [{"start": "00:00", "end": "15:00", "time_period": "off_peak"},
                                    {"start": "15:00", "end": "17:00", "time_period": "on_peak"},
                                    {"start": "17:00", "end": "21:00", "time_period": "mid_peak"},
                                    {"start": "21:00", "end": "24:00", "time_period": "off_peak"}],
                         "time_periods": {"off_peak": {"buy": 0.21626, "sell": 0.03},
                                          "mid_peak": {"buy": 0.54175, "sell": 0.28},
                                          "on_peak": {"buy": 0.54175, "sell": 0.03}}}],
        },
    },
}


def test_to_local_flattens_and_prices():
    util, tar, tz = tariff_io.to_local(AGL["profile"])
    assert util == {"name": "AGL", "network_dnsp": "Ausgrid", "country": "AU", "plan_type": "tou"}
    assert tz == "Australia/Sydney"
    assert tar["name"] == "AGL Energy Ausgrid NSW" and tar["billing_cycle_day"] == 1
    assert tar["charge_window"]["start"] == "10:00"
    assert tar["pricing"]["export_charge_rate"] == 0.013552
    assert tar["pricing"]["export_charge_free_kwh_per_day"] == 6.83
    assert "export_charge" not in tar["pricing"]              # flattened out of pricing
    assert len(tar["fixed_charges"]) == 1
    # the imported seasons price via the SAME rate_model the billing engine uses
    on = rate_model.resolve(tar["pricing"]["seasons"], dt.datetime(2026, 1, 16, 16, 0), 0, None)
    assert on["buy"] == 0.54175 and on["sell"] == 0.03        # 16:00 Jan → on_peak
    mid = rate_model.resolve(tar["pricing"]["seasons"], dt.datetime(2026, 1, 16, 18, 0), 0, None)
    assert mid["buy"] == 0.54175 and mid["sell"] == 0.28      # 18:00 Jan → mid_peak (28c FiT)


def test_round_trip_from_local_renests():
    util, tar, tz = tariff_io.to_local(AGL["profile"])
    tar_row = {"name": tar["name"], "utility_id": "u1",
               **{k: tar[k] for k in ("pricing", "demand_window", "bonus_window",
                                      "charge_window", "fixed_charges")}}
    util_row = {"name": util["name"], "network_dnsp": util["network_dnsp"],
                "country": util["country"], "plan_type": util["plan_type"]}
    out = tariff_io.from_local(util_row, tar_row, tz)
    assert out["type"] == "franklinwh-bridge/tariff-profile"
    p = out["profile"]
    assert p["retailer"] == "AGL" and p["network"] == "Ausgrid" and p["timezone"] == "Australia/Sydney"
    assert p["has_tou"] == 1 and p["has_export_bonus"] == 1
    assert p["pricing"]["export_charge"]["rate"] == 0.013552        # re-nested
    assert p["pricing"]["export_charge"]["free_kwh_per_day"] == 6.83
    assert "export_charge_rate" not in p["pricing"]
    assert p["pricing"]["fixed_charges"][0]["rate"] == 1.58631


def _client(tmp_path, monkeypatch):
    st = MetricsStore(str(tmp_path / "m.db"))
    st.create_site(sid="s1", name="Home")
    st.create_meter(mid="m1", site_id="s1", is_default=True)
    monkeypatch.setattr(environment, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "_settings", None)
    monkeypatch.setattr(db, "get_store", lambda s: st)
    return TestClient(app_module.create_app()), st


def test_import_creates_utility_tariff_and_attaches(tmp_path, monkeypatch):
    c, st = _client(tmp_path, monkeypatch)
    # dry-run preview first
    dry = c.post("/api/tariffs/import?dry_run=true", json={**AGL, "effective_start": "2026-09-09"}).json()
    assert dry["preview"]["retailer"] == "AGL" and dry["preview"]["seasons"] == 1
    # commit
    out = c.post("/api/tariffs/import", json={**AGL, "effective_start": "2026-09-09"}).json()
    assert out["ok"] and out["attached_meter"] == "m1"
    util = st.utility(out["utility_id"])
    assert util["name"] == "AGL" and util["network_dnsp"] == "Ausgrid" and util["effective_start"] == "2026-09-09"
    meter = st.meter("m1")
    assert meter["tariff_id"] == out["tariff_id"] and meter["timezone"] == "Australia/Sydney"
    # a foreign type is rejected clearly
    assert c.post("/api/tariffs/import", json={"type": "nope", "profile": {}}).status_code == 400


def test_export_round_trips_through_the_api(tmp_path, monkeypatch):
    c, st = _client(tmp_path, monkeypatch)
    tid = c.post("/api/tariffs/import", json=AGL).json()["tariff_id"]
    exp = c.get(f"/api/tariffs/{tid}/export").json()
    assert exp["type"] == "franklinwh-bridge/tariff-profile"
    assert exp["profile"]["retailer"] == "AGL"
    assert exp["profile"]["pricing"]["export_charge"]["rate"] == 0.013552
