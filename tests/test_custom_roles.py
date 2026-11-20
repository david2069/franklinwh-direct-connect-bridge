"""Custom roles (standalone only, owner 2026-11-20): an admin names the tabs a role may
open and the actions it may take; the bridge refuses everything else. The built-in roles
are unchanged."""
from test_api_tokens_457 import app, https, store  # noqa: F401 — fixtures
import pytest

from franklinwh_direct_connect_bridge import auth, environment, security

pytestmark = pytest.mark.security_on
PW = "a-long-password"


def _signed_in(app, store, role):  # noqa: F811
    auth.create_user(store, "owner", PW, "admin")
    auth.create_user(store, "kid", PW, role)
    c = https(app)
    assert c.post("/api/auth/login", json={"username": "kid", "password": PW}).status_code == 200
    return c


def test_a_role_is_saved_listed_and_deleted(store):  # noqa: F811
    r = auth.save_role(store, "Dashboard only", ["dashboard", "systemview"], [])
    assert r == {"name": "Dashboard only", "tabs": ["dashboard", "systemview"], "actions": [],
                 "accounts": 0}
    assert [x["name"] for x in auth.roles(store)] == ["Dashboard only"]
    auth.save_role(store, "Dashboard only", ["dashboard"], ["battery"])   # edit in place
    assert auth.custom_role(store, "dashboard only")["actions"] == ["battery"]
    auth.delete_role(store, "Dashboard only")
    assert auth.roles(store) == []


@pytest.mark.parametrize("name,tabs,actions,why", [
    ("admin", ["dashboard"], [], "built-in"),
    ("", ["dashboard"], [], "name"),
    ("x", ["nope"], [], "tab"),
    ("x", ["dashboard"], ["reboot"], "action"),
    ("x", [], [], "at least one tab"),
])
def test_a_bad_role_is_refused(store, name, tabs, actions, why):  # noqa: F811
    with pytest.raises(auth.AuthError, match=why):
        auth.save_role(store, name, tabs, actions)


def test_an_account_can_have_a_custom_role_but_an_api_account_cannot(store):  # noqa: F811
    auth.save_role(store, "Dashboard only", ["dashboard"], [])
    u = auth.create_user(store, "kid", PW, "Dashboard only")
    assert u["role"] == "Dashboard only"
    assert auth.authenticate(store, "kid", PW)
    a = auth.create_user(store, "ha-rest", None, "api")
    with pytest.raises(auth.AuthError):
        auth.update_user(store, a["id"], role="Dashboard only")
    with pytest.raises(auth.AuthError, match="one of"):
        auth.create_user(store, "x", PW, "No such role")


def test_a_role_in_use_cannot_be_deleted(store):  # noqa: F811
    auth.save_role(store, "Dashboard only", ["dashboard"], [])
    auth.create_user(store, "kid", PW, "Dashboard only")
    assert auth.roles(store)[0]["accounts"] == 1
    with pytest.raises(auth.AuthError, match="1 account"):
        auth.delete_role(store, "Dashboard only")


def test_custom_roles_are_standalone_only(store, monkeypatch):  # noqa: F811
    monkeypatch.setattr(environment, "IS_HA_ADDON", True)
    with pytest.raises(auth.AuthError, match="standalone"):
        auth.save_role(store, "Dashboard only", ["dashboard"], [])


def test_the_built_in_roles_are_unchanged():
    assert security.can("user", "POST", "/api/schedules")
    assert security.can("viewer", "GET", "/api/billing/bills")
    assert not security.can("viewer", "POST", "/api/battery/command")


def test_dashboard_only_reads_its_tabs_and_nothing_else(app, store):  # noqa: F811
    auth.save_role(store, "Dashboard only", ["dashboard", "systemview"], [])
    c = _signed_in(app, store, "Dashboard only")
    assert c.get("/api/system").status_code != 403
    assert c.get("/api/version").status_code == 200
    for p in ("/api/logs", "/api/billing/bills", "/api/schedules", "/api/settings"):
        r = c.get(p)
        assert r.status_code == 403 and "Dashboard only" in r.json()["detail"], p
    assert c.post("/api/battery/command", json={}).status_code == 403
    assert c.get("/").status_code == 200                    # the page itself
    assert c.post("/api/auth/password", json={}).status_code != 403   # their own password


def test_actions_allow_battery_commands_and_schedules(app, store):  # noqa: F811
    auth.save_role(store, "Battery", ["dashboard", "battery", "scheduler"], ["battery", "schedules"])
    c = _signed_in(app, store, "Battery")
    assert c.post("/api/battery/command", json={}).status_code != 403
    assert c.post("/api/schedules", json={}).status_code != 403
    assert c.put("/api/settings", json={}).status_code == 403


def test_a_deleted_role_gets_nothing(app, store):  # noqa: F811
    auth.save_role(store, "Gone", ["dashboard"], [])
    c = _signed_in(app, store, "Gone")
    auth._exec(store, "DELETE FROM auth_roles")
    assert c.get("/api/metrics").status_code == 403


def test_me_says_which_tabs(app, store):  # noqa: F811
    auth.save_role(store, "Dashboard only", ["dashboard", "systemview"], [])
    c = _signed_in(app, store, "Dashboard only")
    me = c.get("/api/auth/me").json()
    assert me["tabs"] == ["dashboard", "systemview"] and me["actions"] == []


def test_the_roles_api_is_for_admins(app, store):  # noqa: F811
    auth.create_user(store, "owner", PW, "admin")
    c = https(app)
    c.post("/api/auth/login", json={"username": "owner", "password": PW})
    r = c.post("/api/security/roles", json={"name": "Dashboard only",
                                             "tabs": ["dashboard", "systemview"], "actions": []})
    assert r.status_code == 200, r.text
    d = c.get("/api/security/roles").json()
    assert d["roles"][0]["name"] == "Dashboard only"
    assert {"id": "dashboard", "label": "Dashboard"} in d["tabs"]
    assert c.delete("/api/security/roles/Dashboard only").status_code == 200
    auth.create_user(store, "u", PW, "user")
    u = https(app)
    u.post("/api/auth/login", json={"username": "u", "password": PW})
    assert u.get("/api/security/roles").status_code == 403


def test_setup_is_not_offered_to_a_role_without_settings(app, store, monkeypatch):  # noqa: F811
    from franklinwh_direct_connect_bridge import setup_wizard
    real = setup_wizard.summary
    monkeypatch.setattr(setup_wizard, "summary", lambda *a, **k: {**real(*a, **k), "should_prompt": True})
    auth.save_role(store, "Dashboard only", ["dashboard", "systemview"], [])
    c = _signed_in(app, store, "Dashboard only")
    assert c.get("/api/setup").json()["should_prompt"] is False


def test_the_ui_hides_the_tabs_a_custom_role_lacks():
    from pathlib import Path
    js = (Path(__file__).resolve().parents[1] / "src" / "franklinwh_direct_connect_bridge"
          / "static" / "js" / "app.js").read_text()
    assert "get navPermitted()" in js and "this.navPermitted.map" in js
    assert "if (!this.tabAllowed(name)) return;" in js
