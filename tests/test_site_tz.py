"""/api/site/timezone — the aGate's site timezone, so charts read in aGate-local time."""
import datetime as dt
from fastapi.testclient import TestClient
from franklinwh_local_bridge import (app as app_module, client as client_mod, config,
                                     environment, db)
from franklinwh_local_bridge.db import MetricsStore


def _client(tmp_path, monkeypatch, time_location):
    st = MetricsStore(str(tmp_path / "m.db"))
    monkeypatch.setattr(environment, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "_settings", None)
    monkeypatch.setattr(db, "get_store", lambda s: st)
    monkeypatch.setattr(client_mod, "read", lambda s, name, host=None: dict(time_location))
    return TestClient(app_module.create_app())


def test_site_tz_offset_from_agate_clock(tmp_path, monkeypatch):
    # aGate reports local time 10h ahead of UTC (Sydney AEST) → offset +600 min.
    local = (dt.datetime.utcnow() + dt.timedelta(hours=10)).strftime("%Y-%m-%d %H:%M:%S")
    tl = {"time": local, "timezone": 10, "timezoneStr": "", "DST": 1}
    out = _client(tmp_path, monkeypatch, tl).get("/api/site/timezone").json()
    assert out["available"] is True
    assert out["offset_minutes"] == 600 and out["label"] == "UTC+10"


def test_site_tz_falls_back_to_base_offset(tmp_path, monkeypatch):
    # Unparseable time → fall back to the timezone base-offset hours.
    tl = {"time": "garbage", "timezone": 10, "timezoneStr": "", "DST": 0}
    out = _client(tmp_path, monkeypatch, tl).get("/api/site/timezone").json()
    assert out["available"] is True and out["offset_minutes"] == 600
