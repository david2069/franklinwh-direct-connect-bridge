"""An inverter rating is read, derived or assumed — and it says which.

Owner, 2026-10-16, on the hardcoded 5 kW fallback: "I told earlier Local Bridge that [it]
could [be] determined by model of the aGate and it has mapping in its settings for that
which should be deriving the inverter max power."

The reason it matters: a force command given as a PERCENTAGE is a percentage of this
number. An aPower 2 is 10 kW, so assuming 5 kW halves every dispatch and nothing says so.
"""
import pytest

from franklinwh_direct_connect_bridge import battery_control as bc
from franklinwh_direct_connect_bridge import devicedb
from franklinwh_direct_connect_bridge.db import MetricsStore


@pytest.fixture
def store(tmp_path):
    return MetricsStore(str(tmp_path / "m.db"))


# -- the model mapping -------------------------------------------------------------------
def test_the_datasheet_mapping_scales_with_the_unit_count():
    assert devicedb.apower_power_w("aPower X", 1) == (5000, 5000)
    # Datasheet: charge 8 kW, discharge 10 kW. The 10 in the SKU (APR-10K…) is the
    # DISCHARGE rating — reading it as both directions overstated charging by 25%.
    assert devicedb.apower_power_w("aPower 2", 1) == (8000, 10000)
    assert devicedb.apower_power_w("aPower 2", 3) == (24000, 30000)
    # Asymmetric by datasheet — charging and discharging are not the same number.
    assert devicedb.apower_power_w("aPower S", 1) == (8000, 10000)


def test_an_unknown_model_returns_nothing_rather_than_a_default():
    """"We do not know this model" and "this model is 5 kW" are different answers."""
    assert devicedb.apower_power_w("", 1) is None
    assert devicedb.apower_power_w(None, 1) is None
    assert devicedb.apower_power_w("aPower 9000", 1) is None


# -- the fallback order ------------------------------------------------------------------
def test_modbus_wins_when_it_can_be_read(store, monkeypatch):
    monkeypatch.setattr(bc, "cached_ratings", lambda host: (9000, 11000))
    r = bc.ratings_with_source("192.0.2.110", store=store)
    assert (r["charge_w"], r["discharge_w"]) == (9000, 11000)
    assert r["source"] == "modbus_702" and r["assumed"] is False


def test_the_recorded_apower_model_is_used_when_modbus_cannot_be_read(store, monkeypatch):
    from franklinwh_direct_connect_bridge import system_setup
    monkeypatch.setattr(bc, "cached_ratings", lambda host: (None, None))
    system_setup.update(store, "g1", {"apower_model": "aPower 2"})
    r = bc.ratings_with_source("192.0.2.110", store=store, gateway_id="g1", apower_count=2)
    assert (r["charge_w"], r["discharge_w"]) == (16000, 20000)   # 2 × (8 kW / 10 kW)
    assert r["source"] == "apower_model" and r["assumed"] is False
    assert "aPower 2" in r["detail"]


def test_five_kilowatts_is_the_last_resort_and_says_so(store, monkeypatch):
    monkeypatch.setattr(bc, "cached_ratings", lambda host: (None, None))
    r = bc.ratings_with_source("192.0.2.110", store=store, gateway_id="g1")
    assert r["charge_w"] == bc.ASSUMED_W
    assert r["source"] == "assumed" and r["assumed"] is True
    assert "System Setup" in r["detail"]        # it says how to stop assuming


def test_no_modbus_host_still_answers(store, monkeypatch):
    """A bridge with Modbus off must still size the UI's slider from something."""
    r = bc.ratings_with_source(None, store=store)
    assert r["charge_w"] > 0 and r["source"] in ("apower_model", "user_constant", "assumed")


# -- the dispatch itself -----------------------------------------------------------------
def test_sunspec_ratings_are_never_invented():
    """_ratings() returns None rather than 5000 when the registers do not answer: the
    caller must be able to tell 'unknown' from 'five kilowatts'."""
    class _NoRatings:
        def discover_ratings(self):
            raise OSError("no response")
    assert bc._ratings(_NoRatings()) == (None, None)

    class _Empty:
        def discover_ratings(self): pass
    assert bc._ratings(_Empty()) == (None, None)


def test_a_percentage_is_refused_when_the_rating_is_unknown(monkeypatch):
    """Quietly using 5 kW would halve the dispatch on an aPower 2 and say nothing."""
    class _Ctl:
        commands = []
        def read_control_status(self): return {"wset_enabled": False, "wset_pct": 0}
        def discover_ratings(self): raise OSError("no response")
        def send_command(self, cmd, dry_run=False):
            _Ctl.commands.append(cmd); return True, "sent"
        def disconnect(self): pass
    monkeypatch.setattr(bc, "_ENABLED", True)
    monkeypatch.setattr(bc, "_lib", lambda: (object, lambda **kw: kw))
    monkeypatch.setattr(bc, "_connect", lambda host: (_Ctl(), lambda **kw: kw))
    out = bc.execute("Force Charge", host="192.0.2.110", power_pct=50)
    assert out["ok"] is False
    assert "percentage" in out["result"]
    assert _Ctl.commands == []                  # nothing was written


def test_watts_still_work_without_a_rating(monkeypatch):
    """An explicit wattage needs no rating — refusing that would be gratuitous."""
    sent = []
    class _Ctl:
        def read_control_status(self): return {"wset_enabled": False, "wset_pct": 0}
        def discover_ratings(self): raise OSError("no response")
        def send_command(self, cmd, dry_run=False):
            sent.append(cmd); return True, "sent"
        def disconnect(self): pass
    monkeypatch.setattr(bc, "_ENABLED", True)
    monkeypatch.setattr(bc, "_lib", lambda: (object, lambda **kw: kw))
    monkeypatch.setattr(bc, "_connect", lambda host: (_Ctl(), lambda **kw: kw))
    bc._clear_active()
    out = bc.execute("Force Charge", host="192.0.2.110", power_mode="w", power_w=7000)
    assert out["ok"] is True and sent
    bc._clear_active()


def test_the_apower_2_capacity_and_charge_rate_are_cited():
    """This table said 16 kWh and 10 kW charge; the datasheet says 15 kWh and 8 kW. The
    capacity error flowed into the derived battery-capacity constant (usable × count)."""
    spec = devicedb.APOWER_SPECS["aPower 2"]
    assert spec["usable_kwh"] == 15.0 and spec["rated_kwh"] == 15.0
    assert spec["charge_kw"] == 8.0 and spec["discharge_kw"] == 10.0
    import pathlib
    head = pathlib.Path(devicedb.__file__).read_text().split("APOWER_SPECS")[0]
    assert "apower-2-datasheet" in head and "aPower X-20" in head


def test_both_confirmed_models_charge_slower_than_they_discharge():
    """The trap this table fell into twice: the SKU names the DISCHARGE rating, so
    APR-10K… is a 10 kW discharge / 8 kW charge unit, not 10/10."""
    for model in ("aPower 2", "aPower S"):
        chg, dis = devicedb.apower_power_w(model, 1)
        assert chg == 8000 and dis == 10000, model


def test_the_apower_s_asymmetry_is_cited_to_the_datasheet():
    """It was flagged as uncited; the owner supplied the datasheet and it turned out to be
    right. The citation has to live in the file, because another project is copying this
    table and "the Direct Connect Bridge says 8/10" is not a source."""
    import pathlib
    src = (pathlib.Path(devicedb.__file__)).read_text()
    head = src[:src.index("APOWER_SPECS")]
    assert "V1.9" in head and "franklinwh.com/document/apower-s-datasheet" in head
    assert "8 kW continuous" in head and "10 kW continuous" in head
    assert "device_catalog.json" in head          # the model→SKU mapping


def test_the_with_pv_discharge_figure_is_kept_but_not_used_for_dispatch():
    """11.5 kW includes PV flowing through the hybrid inverter — not what a force command
    controls. Sizing a battery dispatch against it would overshoot by 15%."""
    spec = devicedb.APOWER_SPECS["aPower S"]
    assert spec["discharge_kw"] == 10.0              # battery only
    assert spec["discharge_with_pv_kw"] == 11.5      # recorded, not used
    assert devicedb.apower_power_w("aPower S", 1) == (8000, 10000)


def test_the_au_apower_is_a_distinct_model_not_a_relabel():
    """System datasheet V1.7: aPower X-02-AU is 15 kWh usable / 16 kWh rated at 5 kW,
    where the US aPower X is 13.6 / 15. Treating them as one understates an AU site by
    1.4 kWh per unit — and capacity here is usable_kwh × count."""
    us = devicedb.APOWER_SPECS["aPower X"]
    au = devicedb.APOWER_SPECS["aPower X-02-AU"]
    assert (us["usable_kwh"], us["rated_kwh"]) == (13.6, 15.0)
    assert (au["usable_kwh"], au["rated_kwh"]) == (15.0, 16.0)
    assert us["charge_kw"] == au["charge_kw"] == 5.0          # same rate, different energy
    assert devicedb.apower_power_w("aPower X-02-AU", 4) == (20000, 20000)   # system max 20 kW


def test_the_au_datasheet_is_cited():
    import pathlib
    head = pathlib.Path(devicedb.__file__).read_text().split("APOWER_SPECS")[0]
    assert "system-datasheet" in head and "V1.7" in head
    assert "aPower X-02-AU" in head and "aGate X-01-AU" in head


def test_the_model_picker_offers_the_au_variant():
    from franklinwh_direct_connect_bridge import system_setup
    opts = system_setup.spec()["apower_model"]["options"]
    assert "aPower X-02-AU" in opts and "aPower X" in opts


# -- SKU and country, so the three projects' tables line up --------------------------------
# Owner, 2026-10-16: FWHAI's config model DB table "has SKU and country codes" and needs
# updating with these datasheet figures. Ours now carries both, so the tables can be
# cross-referenced by key rather than by display name.

def test_every_model_carries_its_skus_and_country():
    for model, spec in devicedb.APOWER_SPECS.items():
        assert spec.get("country") in ("US", "AU"), model
        assert spec.get("skus"), model


def test_a_sku_resolves_to_the_right_model():
    assert devicedb.apower_by_sku("APR-10K15V2-US")[0] == "aPower 2"
    assert devicedb.apower_by_sku("APRS-10K15V1-US")[0] == "aPower S"
    # The owner's own hardware, from the AU system datasheet.
    assert devicedb.apower_by_sku("APR-05K15V1-AU")[0] == "aPower X-02-AU"
    # US and AU 5 kW units are different models despite the same rate.
    assert devicedb.apower_by_sku("APR-05K1V1-US")[0] == "aPower X"


def test_an_unknown_sku_is_not_guessed():
    assert devicedb.apower_by_sku("APR-99K99V9-XX") is None
    assert devicedb.apower_by_sku("") is None
