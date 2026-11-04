"""#457 phase 3a: accounts, sign-in on the HTTPS port, roles, and the Security switch."""
import types

import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import app as app_module, auth, db, environment, security, tls
from franklinwh_direct_connect_bridge.db import MetricsStore

pytestmark = pytest.mark.security_on
PW = "correct horse"


@pytest.fixture
def store(tmp_path):
    s = MetricsStore(str(tmp_path / "m.db"))
    auth.ensure_tables(s)
    return s


@pytest.fixture
def app(store, monkeypatch):
    monkeypatch.setattr(db, "get_store", lambda s: store)
    monkeypatch.setattr(tls, "running", lambda: True)
    monkeypatch.setitem(tls.status, "port", 8102)
    a = app_module.create_app()
    assert [u["username"] for u in auth.users(store)] == ["admin"]   # a new install's first admin
    auth._exec(store, "DELETE FROM auth_users")                       # tests add their own
    return a


def https(app):
    return TestClient(app, base_url="https://bridge.lan:8102")


def signed_in(app, store, role, name=None):
    name = name or role
    if not any(u["username"] == name for u in auth.users(store)):
        auth.create_user(store, name, PW, role)
    c = https(app)
    assert c.post("/api/auth/login", json={"username": name, "password": PW}).status_code == 200
    return c


# ── accounts ───────────────────────────────────────────────────────────────────
def test_passwords_are_argon2id_and_checked(store):
    auth.create_user(store, "ann", PW, "user")
    row = auth._rows(store, "SELECT pw_hash FROM auth_users")[0]["pw_hash"]
    assert row.startswith("$argon2id$") and PW not in row
    assert auth.authenticate(store, "ann", PW)["role"] == "user"
    with pytest.raises(auth.AuthError, match="wrong username or password"):
        auth.authenticate(store, "ann", "nope nope")
    with pytest.raises(auth.AuthError, match="wrong username or password"):   # same message
        auth.authenticate(store, "nobody", PW)
    with pytest.raises(auth.AuthError, match="at least 8"):
        auth.create_user(store, "bob", "short", "user")
    with pytest.raises(auth.AuthError, match="already exists"):
        auth.create_user(store, "ANN", PW, "user")
    with pytest.raises(auth.AuthError, match="role"):
        auth.create_user(store, "cat", PW, "api")                # tokens, phase 4


def test_five_failures_in_15_minutes_lock_for_60_seconds(store):
    auth.create_user(store, "ann", PW, "user")
    for i in range(5):
        with pytest.raises(auth.AuthError, match="wrong"):
            auth.authenticate(store, "ann", "bad password", now=1000 + i)
    with pytest.raises(auth.AuthError, match="try again in"):
        auth.authenticate(store, "ann", PW, now=1010)            # even the right password
    assert auth.authenticate(store, "ann", PW, now=1065)          # 60 s later
    for i in range(4):                                            # 4 then a pause: no lock
        with pytest.raises(auth.AuthError, match="wrong"):
            auth.authenticate(store, "ann", "bad password", now=2000 + i)
    with pytest.raises(auth.AuthError, match="wrong"):
        auth.authenticate(store, "ann", "bad password", now=2000 + 16 * 60)
    assert auth.authenticate(store, "ann", PW, now=2000 + 16 * 60 + 1)


def test_disabled_and_expired_accounts_cannot_sign_in(store):
    a = auth.create_user(store, "admin1", PW, "admin")
    u = auth.create_user(store, "ann", PW, "user", expires_at=500)
    with pytest.raises(auth.AuthError, match="expired"):
        auth.authenticate(store, "ann", PW, now=600)
    auth.update_user(store, u["id"], enabled=False, expires_at=None)
    with pytest.raises(auth.AuthError, match="disabled"):
        auth.authenticate(store, "ann", PW)
    assert a["role"] == "admin"


def test_the_last_admin_cannot_be_removed_demoted_disabled_or_expired(store):
    a = auth.create_user(store, "boss", PW, "admin")
    for kw in ({"role": "user"}, {"enabled": False}, {"expires_at": 1.0}):
        with pytest.raises(auth.AuthError, match="last admin"):
            auth.update_user(store, a["id"], **kw)
    with pytest.raises(auth.AuthError, match="last admin"):
        auth.delete_user(store, a["id"])
    auth.create_user(store, "boss2", PW, "admin")
    auth.update_user(store, a["id"], role="viewer")                 # now fine
    assert auth.has_admin(store)


def test_first_admin_from_settings_or_generated_once(store, caplog):
    s = types.SimpleNamespace(admin_username="", admin_password="")
    assert auth.ensure_first_admin(store, s, on_addon=True, security_on=True) is None   # sidebar
    assert auth.ensure_first_admin(store, s, on_addon=False, security_on=False) is None  # upgrade
    assert auth.ensure_first_admin(store, s, on_addon=False, security_on=True) == "generated"
    assert "Password:" in caplog.text and auth.has_admin(store)
    assert auth.ensure_first_admin(store, s, on_addon=False, security_on=True) is None  # once


def test_first_admin_from_admin_username_and_password(tmp_path):
    st = MetricsStore(str(tmp_path / "x.db"))
    auth.ensure_tables(st)
    s = types.SimpleNamespace(admin_username="me", admin_password=PW)
    assert auth.ensure_first_admin(st, s, on_addon=False, security_on=False) == "from settings"
    assert auth.authenticate(st, "me", PW)["role"] == "admin"


def test_reset_password_from_the_command_line(store):
    auth.create_user(store, "boss", PW, "admin")
    for _ in range(5):
        with pytest.raises(auth.AuthError):
            auth.authenticate(store, "boss", "bad password")
    pw = auth.reset_password(store, "boss")
    assert auth.authenticate(store, "boss", pw)
    pw2 = auth.reset_password(store, "newadmin")                    # a new name: an admin
    assert auth.authenticate(store, "newadmin", pw2)["role"] == "admin"


# ── the roles ──────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("method,path,roles", [
    ("POST", "/api/mode", "admin user api"),
    ("POST", "/api/offgrid", "admin user api"),
    ("POST", "/api/dispatch", "admin user api"),
    ("POST", "/api/cloud/reserve", "admin user api"),
    ("POST", "/api/alerts/7/ack", "admin user api"),
    ("POST", "/api/schedules", "admin user"),
    ("PUT", "/api/schedules/3", "admin user"),
    ("PUT", "/api/settings", "admin"),
    ("POST", "/api/ha/instances", "admin"),
    ("PUT", "/api/security/enabled", "admin"),
    ("POST", "/api/circuits/1/power", "admin"),
    ("GET", "/api/summary", "admin user viewer api"),
    ("GET", "/", "admin user viewer"),
    ("GET", "/api/security/users", "admin"),
    ("POST", "/api/auth/logout", "admin user viewer api"),
])
def test_who_may_do_what(method, path, roles):
    assert set(security.required(method, path)) == set(roles.split())


def test_every_write_route_has_a_rule():
    """No write route is left open: anything not listed needs admin."""
    a = app_module.create_app()
    for r in a.routes:
        if r.path.startswith(security.SELF) or r.path in security.SELF:
            continue                                   # your own session and password
        for m in getattr(r, "methods", set()) - {"GET", "HEAD", "OPTIONS"}:
            assert "viewer" not in security.required(m, r.path), (m, r.path)


# ── the switch and the ports ───────────────────────────────────────────────────
def test_upgrade_off_new_install_on(store):
    store.set_config("install_date", "2026-01-01")
    assert security.decide_install(store) == "upgrade" and security.enabled(store) is False


def test_a_new_install_has_security_on(tmp_path):
    st = MetricsStore(str(tmp_path / "n.db"))
    assert security.decide_install(st) == "new" and security.enabled(st) is True


def test_off_means_both_ports_open_without_signing_in(app, store):
    security.set_enabled(store, False)
    assert TestClient(app).get("/api/security").status_code == 200
    assert https(app).put("/api/settings", json={}).status_code != 401


def test_on_8101_redirects_to_https_and_live_stays(app, store):
    security.set_enabled(store, True)
    c = TestClient(app, base_url="http://bridge.lan:8101", follow_redirects=False)
    r = c.get("/api/summary?x=1")
    assert r.status_code == 307 and r.headers["location"] == "https://bridge.lan:8102/api/summary?x=1"
    assert c.get("/api/live").status_code == 200


def test_on_8101_says_why_when_https_is_not_running(app, store, monkeypatch):
    security.set_enabled(store, True)
    monkeypatch.setattr(tls, "running", lambda: False)
    monkeypatch.setitem(tls.status, "error", "could not listen on port 8102")
    r = TestClient(app).get("/")
    assert r.status_code == 503 and "could not listen on port 8102" in r.json()["detail"]


def test_on_https_needs_a_session(app, store):
    security.set_enabled(store, True)
    c = TestClient(app, base_url="https://bridge.lan:8102", follow_redirects=False)
    assert c.get("/api/summary").status_code == 401
    r = c.get("/settings?tab=x")
    assert r.status_code == 303 and r.headers["location"] == "/signin?next=/settings%3Ftab%3Dx"
    assert c.get("/signin").status_code == 200
    assert c.get("/api/auth/me").json()["principal"] is None


def test_sign_in_sets_a_secure_cookie_and_sign_out_ends_it(app, store):
    security.set_enabled(store, True)
    auth.create_user(store, "boss", PW, "admin")
    c = https(app)
    r = c.post("/api/auth/login", json={"username": "boss", "password": PW})
    ck = r.headers["set-cookie"]
    assert "fwh_session=" in ck and "Secure" in ck and "HttpOnly" in ck and "SameSite=lax" in ck
    assert c.get("/api/auth/me").json()["principal"] == {"username": "boss", "role": "admin", "via": "session"}
    assert c.get("/api/summary").status_code != 401
    c.post("/api/auth/logout")
    assert c.get("/api/summary").status_code == 401
    bad = https(app).post("/api/auth/login", json={"username": "boss", "password": "wrong one"})
    assert bad.status_code == 401 and bad.json()["detail"] == "wrong username or password"
    plain = TestClient(app, follow_redirects=False)                   # 8101 sends you to HTTPS
    assert plain.post("/api/auth/login", json={"username": "boss", "password": PW}).status_code == 307


def test_roles_are_enforced(app, store):
    security.set_enabled(store, True)
    auth.create_user(store, "boss", PW, "admin")
    viewer = signed_in(app, store, "viewer")
    r = viewer.put("/api/settings", json={})
    assert r.status_code == 403 and r.json()["detail"] == "Your role (viewer) can't do this."
    assert viewer.post("/api/mode", json={"mode": "self"}).status_code == 403
    assert viewer.get("/api/summary").status_code != 403
    user = signed_in(app, store, "user")
    assert user.post("/api/mode", json={}).status_code != 403        # battery commands: yes
    assert user.post("/api/schedules", json={}).status_code != 403   # schedules: yes
    assert user.put("/api/settings", json={}).status_code == 403      # settings: no
    assert user.get("/api/security/users").status_code == 403


def test_ha_ingress_gets_in_without_signing_in(app, store, monkeypatch):
    security.set_enabled(store, True)
    monkeypatch.setattr(environment, "IS_HA_ADDON", True)
    c = TestClient(app, client=("172.30.32.2", 5000))
    r = c.get("/api/auth/me", headers={"X-Ingress-Path": "/api/hassio_ingress/x",
                                        "X-Remote-User-Name": "dana"})
    assert r.json()["principal"] == {"username": "dana", "role": "admin", "via": "ingress"}


def test_the_switch_needs_an_admin_and_https(app, store, monkeypatch):
    security.set_enabled(store, False)
    c = TestClient(app)
    r = c.put("/api/security/enabled", json={"enabled": True})
    assert r.status_code == 422 and "admin account first" in r.json()["detail"]
    assert c.post("/api/security/users", json={"username": "boss", "password": PW, "role": "admin"}).status_code == 200
    monkeypatch.setattr(tls, "running", lambda: False)
    r = c.put("/api/security/enabled", json={"enabled": True})
    assert r.status_code == 422 and "HTTPS port isn't running" in r.json()["detail"]
    monkeypatch.setattr(tls, "running", lambda: True)
    assert c.put("/api/security/enabled", json={"enabled": True}).json() == {"enabled": True}
    assert security.enabled(store)


def test_change_your_own_password(app, store):
    security.set_enabled(store, True)
    auth.create_user(store, "boss", PW, "admin")
    c = signed_in(app, store, "viewer", "vic")
    r = c.post("/api/auth/password", json={"current": "wrong pass", "new": "a new password"})
    assert r.status_code == 422
    assert c.post("/api/auth/password", json={"current": PW, "new": "a new password"}).status_code == 200
    assert c.get("/api/summary").status_code != 401                  # a fresh session
    assert auth.authenticate(store, "vic", "a new password")


def test_admin_manages_accounts_and_sees_sign_ins(app, store):
    security.set_enabled(store, True)
    admin = signed_in(app, store, "admin", "boss")
    r = admin.post("/api/security/users", json={"username": "ann", "password": PW, "role": "user"})
    uid = r.json()["id"]
    assert admin.patch(f"/api/security/users/{uid}", json={"role": "viewer"}).json()["role"] == "viewer"
    me = [u for u in admin.get("/api/security/users").json()["users"] if u["username"] == "boss"][0]
    r = admin.delete(f"/api/security/users/{me['id']}")
    assert r.status_code == 422 and "last admin" in r.json()["detail"]
    assert admin.delete(f"/api/security/users/{uid}").json() == {"ok": True}
    ev = [e["event"] for e in admin.get("/api/security/signins").json()["events"]]
    assert "signed in" in ev and "deleted" in ev


def test_reset_password_command(store, monkeypatch, capsys):
    from franklinwh_direct_connect_bridge import cli
    monkeypatch.setattr(db, "get_store", lambda s: store)
    assert cli.main(["reset-password", "boss"]) == 0
    pw = capsys.readouterr().out.split("new password ")[1].split()[0]
    assert auth.authenticate(store, "boss", pw)["role"] == "admin"
    assert cli.main(["reset-password"]) == 2


def test_settings_has_the_switch_accounts_and_your_password():
    from pathlib import Path
    root = Path(app_module.__file__).parent
    html = (root / "templates/tabs/settings.html").read_text()
    for s in ('data-testid="security-toggle"', 'data-testid="accounts-section"', "addAccount()",
              "resetAccountPassword(u)", "deleteAccount(u)", 'data-testid="signin-activity"',
              "changeMyPassword()", "signOut()", "dialog_msg('security.switchMsg')",
              "dialog_msg('security.acctMsg')"):
        assert s in html, s
    idx = (root / "templates/index.html").read_text()
    assert "r.status === 401" in idx and "/signin?next=" in idx
    sign = (root / "templates/signin.html").read_text()
    assert "!raw.startsWith('//')" in sign                      # no redirect to another site
