"""A recording survives the aGate dropping off, and says why and by whom it ended.

Owner, 2026-11-14: a recording of Emergency Backup ended after 13 of 200 samples, and
the bridge's log could not say why — Stop was not logged, nor who pressed it.
"""

import logging
import time

import pytest

from franklinwh_direct_connect_bridge import bms_record
from franklinwh_direct_connect_bridge.bms_record import Recorder
from franklinwh_direct_connect_bridge.db import MetricsStore

from test_bms_sessions import api, cells  # noqa: F401 — the REST fixture


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(bms_record, "MIN_INTERVAL_S", 0.01)


def _wait(r):
    t = time.time() + 10
    while r.status()["active"] and time.time() < t:
        time.sleep(0.01)
    assert not r.status()["active"]


def test_failed_reads_do_not_use_up_the_planned_samples():
    s, r = MetricsStore(":memory:"), Recorder()
    n = {"i": 0}

    def outage():
        n["i"] += 1
        if 2 <= n["i"] <= 4:
            raise ConnectionRefusedError("aGate refused")
        return cells()

    r.start(s, outage, samples=3, interval_s=0.01)
    _wait(r)
    st = r.status()
    assert st["captured"] == 3 and st["errors"] == 3
    sess = s.bms_session(st["session_id"])
    assert len(sess["samples"]) == 3 and sess["end_reason"] == "completed"


def test_a_read_with_no_cell_data_is_a_failed_read():
    s, r = MetricsStore(":memory:"), Recorder()
    out = iter([None, cells(), cells()])
    r.start(s, lambda: next(out), samples=2, interval_s=0.01)
    _wait(r)
    assert r.status()["captured"] == 2 and r.status()["errors"] == 1


def test_gives_up_when_the_agate_stays_unreachable(monkeypatch, caplog):
    monkeypatch.setattr(bms_record, "GIVE_UP_AFTER_S", 0.2)
    s, r = MetricsStore(":memory:"), Recorder()

    def down():
        raise ConnectionRefusedError("aGate refused")

    with caplog.at_level(logging.INFO, logger=bms_record.__name__):
        r.start(s, down, samples=5, interval_s=0.01)
        _wait(r)
    st = r.status()
    assert st["captured"] == 0 and st["end_reason"].startswith("aGate unreachable for")
    assert s.bms_session(st["session_id"])["end_reason"] == st["end_reason"]
    assert any("ended" in m and "unreachable" in m for m in caplog.messages)


def test_start_stop_and_who_are_logged_and_kept(caplog):
    s, r = MetricsStore(":memory:"), Recorder()
    with caplog.at_level(logging.INFO, logger=bms_record.__name__):
        r.start(s, lambda: cells(), samples=10_000, interval_s=0.01, by="admin (session)")
        time.sleep(0.05)
        r.stop(by="admin (session)")
        _wait(r)
    sid = r.status()["session_id"]
    assert s.bms_session(sid)["end_reason"] == "stopped by admin (session)"
    assert any(f"session {sid} started by admin (session)" in m for m in caplog.messages)
    assert any(f"session {sid} stop requested by admin (session)" in m
               for m in caplog.messages)
    assert any(f"session {sid} ended: stopped by admin (session)" in m
               for m in caplog.messages)


def test_end_reason_survives_a_reopen(tmp_path):
    path = str(tmp_path / "m.db")
    s = MetricsStore(path)
    sid = s.start_bms_session()
    s.end_bms_session(sid, reason="completed")
    s.close()
    s = MetricsStore(path)
    assert s.bms_sessions()[0]["end_reason"] == "completed"
    s.close()


def test_stop_endpoint_logs_the_caller(api, caplog, monkeypatch):  # noqa: F811
    store = MetricsStore(":memory:")
    rec = bms_record.get_recorder()
    rec.start(store, lambda: cells(), samples=10_000, interval_s=0.01)
    with caplog.at_level(logging.INFO, logger=bms_record.__name__):
        assert api.post("/api/battery/record/stop").status_code == 200
        _wait(rec)
    # Security off and not HA's sidebar: nobody is signed in, so the address it came from.
    assert any("stop requested by testclient (not signed in)" in m for m in caplog.messages)
    assert rec.status()["end_reason"] == "stopped by testclient (not signed in)"


def test_the_battery_tab_shows_why_a_recording_ended():
    from pathlib import Path
    root = Path(bms_record.__file__).parent
    html = (root / "templates/tabs/battery.html").read_text()
    js = (root / "static/js/battery_tab.js").read_text()
    assert html.count("'Ended: ' + s.end_reason") == 1          # the recordings list
    assert html.count("'Ended: ' + session.end_reason") == 1    # the open recording
    assert "this.rec.end_reason" in js                          # "Recording saved: …"
