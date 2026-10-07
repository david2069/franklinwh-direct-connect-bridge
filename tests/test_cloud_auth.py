"""Cloud-auth breaker: persistence, staleness, revalidation policy, API exposure."""

import json
import time

import pytest

from franklinwh_direct_connect_bridge import config, environment, providers
from franklinwh_direct_connect_bridge.config import Settings


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """Fresh DATA_DIR, clean breaker, and a clean Settings singleton per test.

    The settings singleton is process-global and the API tests below write
    credentials into it, so without resetting it a later test sees a previous
    test's password and "unconfigured" never happens.
    """
    monkeypatch.setattr(environment, "DATA_DIR", str(tmp_path))
    providers._cloud_auth.update(state="unknown", fail_count=0, error=None, checked_at=0.0)
    providers._breaker_loaded = False
    monkeypatch.setattr(config, "_settings", None)
    yield
    config._settings = None


def _creds(**kw) -> Settings:
    s = Settings()
    s.fwh_cloud_email = kw.get("email", "a@b.c")
    s.fwh_cloud_password = kw.get("password", "pw")
    s.fwh_cloud_gateway = kw.get("gateway", "")
    return s


# -- status snapshot ---------------------------------------------------------
def test_status_reports_age_and_staleness():
    providers._cloud_auth.update(state="valid", checked_at=time.time())
    st = providers.cloud_auth_status()
    assert st["state"] == "valid"
    assert st["age_s"] is not None and st["age_s"] < 5
    assert st["stale"] is False
    assert st["max_fails"] == providers._MAX_AUTH_FAILS


def test_old_valid_is_marked_stale():
    """'valid' from last week must not look like 'valid just now'."""
    providers._cloud_auth.update(
        state="valid", checked_at=time.time() - providers.REVALIDATE_AFTER_S - 60)
    assert providers.cloud_auth_status()["stale"] is True


def test_never_checked_has_no_age():
    assert providers.cloud_auth_status()["age_s"] is None


# -- breaker behaviour -------------------------------------------------------
def test_breaker_locks_after_max_failures():
    for _ in range(providers._MAX_AUTH_FAILS):
        providers._note_auth_failure("bad password")
    assert providers.cloud_auth_status()["state"] == "locked"


def test_failure_before_the_cap_is_invalid_not_locked():
    providers._note_auth_failure("bad password")
    assert providers.cloud_auth_status()["state"] == "invalid"


def test_breaker_survives_a_restart(tmp_path):
    """A module global resets on restart; a restart loop would then burn three
    fresh login failures per cycle — the very lockout this guards against."""
    for _ in range(providers._MAX_AUTH_FAILS):
        providers._note_auth_failure("bad password")
    providers._save_breaker()
    saved = json.loads((tmp_path / "overrides.json").read_text())
    assert saved[providers._BREAKER_KEY]["state"] == "locked"

    # simulate a restart
    providers._cloud_auth.update(state="unknown", fail_count=0, error=None, checked_at=0.0)
    providers._breaker_loaded = False
    assert providers.cloud_auth_status()["state"] == "locked"


def test_reset_clears_a_locked_breaker_on_disk_too():
    for _ in range(providers._MAX_AUTH_FAILS):
        providers._note_auth_failure("bad")
    providers.reset_cloud_breaker()
    assert providers.cloud_auth_status()["state"] == "unknown"
    providers._breaker_loaded = False                     # re-read from disk
    assert providers.cloud_auth_status()["state"] == "unknown"


def test_breaker_state_is_not_applied_onto_settings():
    """It persists via save_override_raw, so it must not leak into Settings."""
    providers._note_auth_failure("bad")
    providers._save_breaker()
    s = Settings()
    config.apply_overrides(s)
    assert not hasattr(s, providers._BREAKER_KEY)
    assert providers._BREAKER_KEY not in config._OVERRIDE_KEYS


# -- revalidation policy -----------------------------------------------------
def test_revalidation_not_due_without_credentials():
    assert providers.revalidate_due(Settings()) is False


def test_revalidation_due_when_never_checked():
    assert providers.revalidate_due(_creds()) is True


def test_revalidation_not_due_immediately_after_a_check():
    providers._cloud_auth.update(state="valid", checked_at=time.time())
    assert providers.revalidate_due(_creds()) is False


def test_revalidation_due_once_stale():
    providers._cloud_auth.update(
        state="valid", checked_at=time.time() - providers.REVALIDATE_AFTER_S - 1)
    assert providers.revalidate_due(_creds()) is True


def test_locked_breaker_is_never_auto_retried():
    """Protecting the account beats keeping the status fresh."""
    providers._cloud_auth.update(state="locked", fail_count=9, checked_at=0.0)
    assert providers.revalidate_due(_creds()) is False


def test_validate_without_credentials_reports_unconfigured():
    assert providers.validate_cloud(Settings())["state"] == "unconfigured"


def test_validate_refuses_to_attempt_when_locked(monkeypatch):
    called = []
    monkeypatch.setattr(providers, "_cloud_login_check",
                        lambda *a: called.append(1))
    providers._cloud_auth.update(state="locked", fail_count=3)
    assert providers.validate_cloud(_creds())["state"] == "locked"
    assert called == []                                   # no login attempted


def test_validate_records_success_and_timestamp(monkeypatch):
    monkeypatch.setattr(providers, "_cloud_login_check", lambda *a: None)
    st = providers.validate_cloud(_creds())
    assert st["state"] == "valid"
    assert st["fail_count"] == 0
    assert st["age_s"] is not None


def test_validate_records_the_failure_reason(monkeypatch):
    def _boom(*a):
        raise RuntimeError("401 unauthorized")
    monkeypatch.setattr(providers, "_cloud_login_check", _boom)
    st = providers.validate_cloud(_creds())
    assert st["state"] == "invalid"
    assert "401" in st["error"]


# -- API surface -------------------------------------------------------------
def _api(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from franklinwh_direct_connect_bridge import app as app_module
    monkeypatch.setattr(environment, "DATA_DIR", str(tmp_path))
    return TestClient(app_module.create_app())


def test_settings_exposes_cloud_block_without_the_password(monkeypatch, tmp_path):
    """The password must never come back out — only whether one is set."""
    c = _api(monkeypatch, tmp_path)
    r = c.put("/api/settings", json={"fwh_cloud_email": "a@b.c",
                                     "fwh_cloud_password": "s3cret",
                                     "fwh_cloud_gateway": "abc123"})
    assert r.status_code == 200
    cloud = r.json()["cloud"]
    assert cloud["email"] == "a@b.c"
    assert cloud["password_set"] is True
    assert cloud["gateway"] == "ABC123"           # upper-cased for the cloud
    assert "s3cret" not in r.text
    assert "password" not in set(cloud) - {"password_set"}


def test_credentials_are_strings_not_coerced_to_bool(monkeypatch, tmp_path):
    """The generic settings branch coerces to bool — these must bypass it."""
    c = _api(monkeypatch, tmp_path)
    c.put("/api/settings", json={"fwh_cloud_email": "user@example.com"})
    assert c.get("/api/settings").json()["cloud"]["email"] == "user@example.com"


def test_changing_credentials_clears_a_locked_breaker(monkeypatch, tmp_path):
    """Editing the credentials is the documented way out of a lockout."""
    c = _api(monkeypatch, tmp_path)
    for _ in range(providers._MAX_AUTH_FAILS):
        providers._note_auth_failure("bad")
    assert providers.cloud_auth_status()["state"] == "locked"
    c.put("/api/settings", json={"fwh_cloud_password": "a-new-password"})
    assert providers.cloud_auth_status()["state"] == "unknown"


def test_rewriting_the_same_value_does_not_reset_the_breaker(monkeypatch, tmp_path):
    c = _api(monkeypatch, tmp_path)
    c.put("/api/settings", json={"fwh_cloud_password": "pw"})
    providers._note_auth_failure("bad")
    c.put("/api/settings", json={"fwh_cloud_password": "pw"})   # unchanged
    assert providers.cloud_auth_status()["state"] == "invalid"


def test_validate_endpoint_returns_the_auth_snapshot(monkeypatch, tmp_path):
    c = _api(monkeypatch, tmp_path)
    r = c.post("/api/cloud/validate")
    assert r.status_code == 200
    body = r.json()
    assert body["state"] == "unconfigured"        # no credentials set
    assert {"state", "error", "checked_at", "age_s", "stale", "max_fails"} <= set(body)


def test_settings_reports_auth_state(monkeypatch, tmp_path):
    c = _api(monkeypatch, tmp_path)
    auth = c.get("/api/settings").json()["cloud"]["auth"]
    assert "state" in auth and "stale" in auth


# -- transient vs rejection: a bad network must not lock the account ---------
def test_network_failure_does_not_count_toward_lockout(monkeypatch):
    """A bad network week must never lock reserve control."""
    def _boom(*a):
        raise TimeoutError("connection timed out")
    monkeypatch.setattr(providers, "_cloud_login_check", _boom)
    for _ in range(providers._MAX_AUTH_FAILS + 2):
        st = providers.validate_cloud(_creds())
    assert st["state"] == "unreachable"
    assert st["fail_count"] == 0


def test_rejected_credentials_do_count(monkeypatch):
    def _boom(*a):
        raise RuntimeError("401 unauthorized")
    monkeypatch.setattr(providers, "_cloud_login_check", _boom)
    for _ in range(providers._MAX_AUTH_FAILS):
        st = providers.validate_cloud(_creds())
    assert st["state"] == "locked"


def test_rejection_is_recognised_by_exception_name():
    class InvalidCredentialsException(Exception):
        pass
    assert providers._is_auth_rejection(InvalidCredentialsException("nope"))
    assert providers._is_auth_rejection(RuntimeError("HTTP 403 Forbidden"))
    assert not providers._is_auth_rejection(TimeoutError("timed out"))
    assert not providers._is_auth_rejection(OSError("dns failure"))


def test_unreachable_is_retried_sooner_than_valid_is_rechecked():
    providers._cloud_auth.update(
        state="unreachable", checked_at=time.time() - providers.RETRY_UNREACHABLE_AFTER_S - 1)
    assert providers.revalidate_due(_creds()) is True
    providers._cloud_auth.update(state="valid", checked_at=time.time() - 3600)
    assert providers.revalidate_due(_creds()) is False


def test_unreachable_never_becomes_locked_on_its_own(monkeypatch):
    def _boom(*a):
        raise OSError("network unreachable")
    monkeypatch.setattr(providers, "_cloud_login_check", _boom)
    for _ in range(20):
        providers.validate_cloud(_creds())
    assert providers.cloud_auth_status()["state"] != "locked"
