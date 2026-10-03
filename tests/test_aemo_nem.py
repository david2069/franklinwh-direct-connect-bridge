"""AEMO NEM wholesale spot — module + snapshot + endpoint (FEAT-BILLING-WHOLESALE)."""
import io, json
from fastapi.testclient import TestClient
from franklinwh_local_bridge import aemo_nem, scheduler, app as app_module


class _Resp(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): return False


def test_spot_price_and_conversion(monkeypatch):
    payload = {"ELEC_NEM_SUMMARY": [
        {"REGIONID": "NSW1", "PRICE": 67.18, "SETTLEMENTDATE": "2026-09-29T08:55:00"},
        {"REGIONID": "VIC1", "PRICE": -20.0, "SETTLEMENTDATE": "2026-09-29T08:55:00"}]}
    monkeypatch.setattr(aemo_nem.urllib.request, "urlopen",
                        lambda req, timeout=0: _Resp(json.dumps(payload).encode()))
    aemo_nem._cache.clear()
    sp = aemo_nem.spot_price("NSW1")
    assert sp["rrp_mwh"] == 67.18 and sp["price_c_kwh"] == 6.72 and sp["region"] == "NSW1"
    assert aemo_nem.spot_price("VIC1")["price_c_kwh"] == -2.0   # negative — paid to consume
    assert aemo_nem.spot_price("BOGUS") is None                 # not a NEM region


def test_nem_snapshot(monkeypatch):
    monkeypatch.setattr(aemo_nem, "spot_price",
                        lambda r: {"price_c_kwh": 6.72} if r == "NSW1" else None)

    class S:  nem_region = "NSW1"
    class Soff: nem_region = ""
    assert scheduler.nem_snapshot(S())["tariff.spot_price"] == 6.72
    assert scheduler.nem_snapshot(Soff()) == {}                 # not configured -> empty


def test_spot_endpoint(monkeypatch):
    monkeypatch.setattr(aemo_nem, "spot_price",
                        lambda r: {"region": r, "price_c_kwh": 6.72} if r == "NSW1" else None)
    out = TestClient(app_module.create_app()).get("/api/tariff/spot?region=NSW1").json()
    assert out["region"] == "NSW1" and out["spot"]["price_c_kwh"] == 6.72
    assert "NSW1" in out["regions"] and "VIC1" in out["regions"]


def test_settings_put_nem_region_is_string(tmp_path, monkeypatch):
    """Regression: nem_region must persist as a STRING (the generic PUT branch bool-coerced it)."""
    from franklinwh_local_bridge import environment, config, providers
    monkeypatch.setattr(environment, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "_settings", None)
    # Driving the app under a tmp DATA_DIR triggers the once-only cloud-breaker load against
    # an empty dir, which would poison the module globals for later cloud tests. Snapshot and
    # restore them so the next accessor re-reads the real breaker.
    _auth_snapshot = dict(providers._cloud_auth)
    _loaded_snapshot = providers._breaker_loaded

    def _restore_breaker():
        providers._cloud_auth.clear()
        providers._cloud_auth.update(_auth_snapshot)
        providers._breaker_loaded = _loaded_snapshot
    monkeypatch.setattr(providers, "_restore_hook_unused", 0, raising=False)
    try:
        c = TestClient(app_module.create_app())
        assert c.put("/api/settings", json={"nem_region": "NSW1"}).status_code == 200
        assert config.get_settings().nem_region == "NSW1"          # string, not True
        assert c.put("/api/settings", json={"nem_region": "BOGUS"}).status_code == 422
        assert c.put("/api/settings", json={"nem_region": ""}).status_code == 200   # clears
    finally:
        _restore_breaker()


def test_ha_price_snapshot_units_and_mapping(monkeypatch):
    """HA price entity -> tariff.spot_price / feed_in_price, with $/kWh auto-scaled to cents."""
    from franklinwh_local_bridge import scheduler, ha_instances

    class S:
        tariff_price_entity = "ha:h1:sensor.buy"
        tariff_feedin_entity = "ha:h1:sensor.sell"

    class Store:
        def ha_instances(self):
            return [{"id": "h1", "base_url": "http://x", "token": "t", "enabled": 1}]

    states = [
        {"entity_id": "sensor.buy", "state": "12.46", "attributes": {"unit_of_measurement": "¢/kWh"}},
        {"entity_id": "sensor.sell", "state": "0.28", "attributes": {"unit_of_measurement": "$/kWh"}},
    ]
    monkeypatch.setattr(ha_instances, "states", lambda b, t: states)
    out = scheduler.ha_price_snapshot(S(), Store())
    assert out["tariff.spot_price"] == 12.46          # c/kWh taken as-is
    assert out["tariff.feed_in_price"] == 28.0        # $0.28/kWh -> 28 c/kWh


def test_ha_price_snapshot_empty_when_unset():
    from franklinwh_local_bridge import scheduler

    class S:
        tariff_price_entity = ""
        tariff_feedin_entity = ""

    assert scheduler.ha_price_snapshot(S(), object()) == {}


def test_settings_put_tariff_entities_are_strings(tmp_path, monkeypatch):
    """Regression: the tariff HA-entity settings must persist as STRINGS (the generic PUT
    branch would bool-coerce them, like nem_region did)."""
    from franklinwh_local_bridge import environment, config, providers
    monkeypatch.setattr(environment, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "_settings", None)
    _auth = dict(providers._cloud_auth)
    _loaded = providers._breaker_loaded
    try:
        c = TestClient(app_module.create_app())
        eid = "ha:h1:sensor.amber_express_home_general_price"
        assert c.put("/api/settings", json={"tariff_price_entity": eid}).status_code == 200
        assert config.get_settings().tariff_price_entity == eid   # string, not True
        assert c.put("/api/settings", json={"tariff_price_entity": ""}).status_code == 200
        assert config.get_settings().tariff_price_entity == ""
    finally:
        providers._cloud_auth.clear(); providers._cloud_auth.update(_auth)
        providers._breaker_loaded = _loaded
