"""Each installation has its own identity (owner, 2026-11-11): a random install id, how it
was installed, the OS, Python and bridge version and since when — kept in the bridge's
own store and shown in the support info so a report can be read at a glance."""
import re
import uuid

from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import install_identity as ii
from franklinwh_direct_connect_bridge.db import MetricsStore


def test_the_id_is_made_once_and_kept(tmp_path):
    st = MetricsStore(str(tmp_path / "m.db"))
    ii.ensure(st, "0.5.40")
    first = st.get_config("install_id")
    uuid.UUID(first)                                    # a real UUID
    assert st.get_config("first_version") == "0.5.40"
    ii.ensure(st, "0.5.41")                             # restart after an update
    assert st.get_config("install_id") == first
    assert st.get_config("first_version") == "0.5.40"


def test_install_type(monkeypatch):
    exists = set()
    monkeypatch.setattr(ii, "_exists", lambda p: p in exists)
    monkeypatch.setattr(ii, "_source_checkout", lambda: False)
    monkeypatch.setattr(ii, "_supervisor_info", lambda: {})
    assert ii.install_type() == "pip"
    monkeypatch.setattr(ii, "_source_checkout", lambda: True)
    assert ii.install_type() == "dev"
    exists.add("/run/.containerenv")
    assert ii.install_type() == "podman"
    exists.clear(); exists.add("/.dockerenv")
    assert ii.install_type() == "docker"
    exists.add("/data/options.json")
    monkeypatch.setattr(ii, "_supervisor_info", lambda: {"hassos": "13.2"})
    assert ii.install_type() == "ha_addon_haos"
    monkeypatch.setattr(ii, "_supervisor_info", lambda: {"hassos": None})
    assert ii.install_type() == "ha_addon_supervised"
    monkeypatch.setattr(ii, "_supervisor_info", lambda: None)
    assert ii.install_type() == "ha_addon"            # Supervisor didn't answer


def test_facts(tmp_path, monkeypatch):
    st = MetricsStore(str(tmp_path / "m.db"))
    monkeypatch.setattr(ii, "_supervisor_info",
                        lambda: {"hassos": "13.2", "homeassistant": "2026.11.1",
                                 "operating_system": "Home Assistant OS 13.2"})
    monkeypatch.setattr(ii, "_exists", lambda p: p == "/data/options.json")
    ii.ensure(st, "0.5.40")
    st.set_config("install_date", "2026-10-15")
    f = ii.facts(st, "0.5.40")
    assert f["install_id"] == st.get_config("install_id")
    assert f["install_type"] == "ha_addon_haos"
    assert f["os"] == "Home Assistant OS 13.2"
    assert f["home_assistant"] == "2026.11.1"
    assert re.fullmatch(r"\d+\.\d+\.\d+.*", f["python"])
    assert f["arch"] and f["bridge_version"] == "0.5.40"
    assert f["install_date"] == "2026-10-15" and f["first_version"] == "0.5.40"


def test_support_info_carries_the_identity(tmp_path, monkeypatch):
    from franklinwh_direct_connect_bridge import app as app_module, config, environment, db
    st = MetricsStore(str(tmp_path / "m.db"))
    monkeypatch.setattr(environment, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "_settings", None)
    monkeypatch.setattr(db, "get_store", lambda s: st)
    c = TestClient(app_module.create_app())
    m = c.get("/api/support-info").json()["meta"]
    inst = m["install"]
    assert inst["install_id"] == st.get_config("install_id")
    for k in ("install_type", "os", "arch", "python", "bridge_version", "install_date",
              "first_version"):
        assert k in inst, k
    from pathlib import Path
    js = (Path(__file__).resolve().parents[1]
          / "src/franklinwh_direct_connect_bridge/static/js/settings_tab.js").read_text()
    assert "m.install" in js and "install_id" in js
