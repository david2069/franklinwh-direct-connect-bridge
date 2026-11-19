"""Quick start outside Home Assistant: SECURITY=off on the first start makes a new install
start with Security off (no sign-in, no generated admin); trusted networks stay private."""
import pytest

from franklinwh_direct_connect_bridge import auth, security
from franklinwh_direct_connect_bridge.config import Settings
from franklinwh_direct_connect_bridge.db import MetricsStore

pytestmark = pytest.mark.security_on


def test_security_off_on_the_first_start_makes_a_new_install_start_off(tmp_path):
    st = MetricsStore(str(tmp_path / "q.db"))
    assert security.decide_install(st, quick_start=True) == "new"
    assert security.enabled(st) is False
    assert security.trusted_networks(st) == security.PRIVATE
    assert security.quick_start(st) is True


def test_no_admin_is_generated_on_a_quick_start(tmp_path):
    st = MetricsStore(str(tmp_path / "q.db"))
    security.decide_install(st, quick_start=True)
    auth.ensure_tables(st)
    assert auth.ensure_first_admin(st, Settings(), on_addon=False,
                                   security_on=security.enabled(st)) is None
    assert not auth.has_admin(st)


def test_it_is_read_only_on_the_first_start(tmp_path):
    st = MetricsStore(str(tmp_path / "q.db"))
    security.decide_install(st)                               # first start: on
    assert security.decide_install(st, quick_start=True) == "new"
    assert security.enabled(st) is True and security.quick_start(st) is False


def test_an_upgrade_ignores_it(tmp_path):
    st = MetricsStore(str(tmp_path / "q.db"))
    st.set_config("install_date", "2026-01-01")
    security.decide_install(st, quick_start=True)
    assert security.enabled(st) is False and security.quick_start(st) is False


def test_the_setting_reads_security_off(monkeypatch):
    monkeypatch.setenv("SECURITY", "off")
    assert Settings().security_quick_start is True
    monkeypatch.setenv("SECURITY", "on")
    assert Settings().security_quick_start is False
    monkeypatch.delenv("SECURITY")
    assert Settings().security_quick_start is False


def test_the_security_page_says_quick_start(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from franklinwh_direct_connect_bridge import app as app_module, db
    st = MetricsStore(str(tmp_path / "q.db"))
    security.decide_install(st, quick_start=True)
    monkeypatch.setattr(db, "get_store", lambda s=None: st)
    r = TestClient(app_module.create_app()).get("/api/security").json()
    assert r["quick_start"] is True and r["enabled"] is False
