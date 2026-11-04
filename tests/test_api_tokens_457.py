"""#457 phase 4: API tokens and the api role."""
import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import app as app_module, auth, db, security, tls
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
    auth._exec(store, "DELETE FROM auth_users")
    security.set_enabled(store, True)
    return a


def https(app, token=None):
    c = TestClient(app, base_url="https://bridge.lan:8102", follow_redirects=False)
    if token:
        c.headers["Authorization"] = f"Bearer {token}"
    return c


def test_api_accounts_have_no_password_and_cannot_sign_in(store):
    a = auth.create_user(store, "ha-rest", None, "api")
    assert a["role"] == "api" and a["has_password"] is False
    with pytest.raises(auth.AuthError, match="wrong username or password"):
        auth.authenticate(store, "ha-rest", "")
    with pytest.raises(auth.AuthError, match="no password"):
        auth.update_user(store, a["id"], password="something long")
    with pytest.raises(auth.AuthError, match="can't become"):
        auth.update_user(store, a["id"], role="user")


def test_a_token_is_shown_once_kept_as_a_hash_and_expires(store):
    u = auth.create_user(store, "ha-rest", None, "api")
    tok, info = auth.create_token(store, u["id"], "HA REST sensor", 30, now=1000)
    assert tok.startswith("fwhdc_") and len(tok) > 40 and info["hint"] == tok[-4:]
    assert tok not in str(auth._rows(store, "SELECT * FROM auth_tokens"))     # hash only
    assert auth.token_user(store, tok, now=1000 + 29 * 86400)["username"] == "ha-rest"
    assert auth.token_user(store, tok, now=1000 + 31 * 86400) is None          # expired
    assert auth.token_user(store, "fwhdc_nope", now=1000) is None
    with pytest.raises(auth.AuthError, match="days"):
        auth.create_token(store, u["id"], "x", 7)
    with pytest.raises(auth.AuthError, match="name"):
        auth.create_token(store, u["id"], "  ", 30)


def test_revoking_disabling_or_deleting_ends_a_token(store):
    auth.create_user(store, "boss", PW, "admin")
    u = auth.create_user(store, "ha-rest", None, "api")
    tok, info = auth.create_token(store, u["id"], "one", 90)
    auth.update_user(store, u["id"], enabled=False)
    assert auth.token_user(store, tok) is None
    auth.update_user(store, u["id"], enabled=True)
    assert auth.token_user(store, tok)
    auth.revoke_token(store, info["id"])
    assert auth.token_user(store, tok) is None
    tok2, _ = auth.create_token(store, u["id"], "two", 90)
    auth.delete_user(store, u["id"])
    assert auth.token_user(store, tok2) is None and auth.tokens(store) == []


def test_last_used_is_kept_without_writing_every_call(store):
    u = auth.create_user(store, "ha-rest", None, "api")
    tok, info = auth.create_token(store, u["id"], "one", 30, now=1000)
    auth.token_user(store, tok, now=1100)
    auth.token_user(store, tok, now=1120)                      # within a minute: not rewritten
    assert auth.tokens(store, now=1200)[0]["last_used"] == 1100
    auth.token_user(store, tok, now=1170)
    assert auth.tokens(store, now=1200)[0]["last_used"] == 1170


def test_a_bearer_token_works_on_https_with_its_accounts_role(app, store):
    u = auth.create_user(store, "ha-rest", None, "api")
    tok, _ = auth.create_token(store, u["id"], "rest", 365)
    c = https(app, tok)
    me = c.get("/api/auth/me").json()["principal"]
    assert me == {"username": "ha-rest", "role": "api", "via": "token"}
    assert c.get("/api/summary").status_code not in (401, 403)          # reads
    assert c.post("/api/mode", json={}).status_code not in (401, 403)   # battery commands
    assert c.post("/api/schedules", json={}).status_code == 403          # not schedules
    assert c.put("/api/settings", json={}).status_code == 403
    assert c.get("/").status_code == 403                                 # no web UI


def test_a_bad_token_is_401_even_with_a_session(app, store):
    auth.create_user(store, "boss", PW, "admin")
    c = https(app)
    c.post("/api/auth/login", json={"username": "boss", "password": PW})
    assert c.get("/api/gateways").status_code == 200
    r = c.get("/api/gateways", headers={"Authorization": "Bearer fwhdc_wrong"})
    assert r.status_code == 401 and r.json()["detail"] == "Invalid or expired API token."


def test_admin_creates_lists_and_revokes_tokens(app, store):
    auth.create_user(store, "boss", PW, "admin")
    admin = https(app)
    admin.post("/api/auth/login", json={"username": "boss", "password": PW})
    a = admin.post("/api/security/users", json={"username": "ha-rest", "role": "api"}).json()
    assert a["role"] == "api"
    r = admin.post("/api/security/tokens", json={"user_id": a["id"], "name": "HA", "days": 90}).json()
    tok = r["token"]
    listed = admin.get("/api/security/tokens").json()
    assert listed["days"] == [30, 90, 365] and "token" not in listed["tokens"][0]
    assert listed["tokens"][0]["hint"] == tok[-4:]
    assert https(app, tok).get("/api/gateways").status_code == 200
    assert https(app, tok).get("/api/security/tokens").status_code == 403    # api can't list
    assert admin.delete(f"/api/security/tokens/{r['id']}").json() == {"ok": True}
    assert https(app, tok).get("/api/gateways").status_code == 401


def test_a_token_is_ignored_on_8101(app, store):
    u = auth.create_user(store, "ha-rest", None, "api")
    tok, _ = auth.create_token(store, u["id"], "rest", 30)
    c = TestClient(app, base_url="http://bridge.lan:8101", follow_redirects=False)
    r = c.get("/api/summary", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 307                                          # sent to HTTPS


def test_settings_has_tokens():
    from pathlib import Path
    html = (Path(app_module.__file__).parent / "templates/tabs/settings.html").read_text()
    for s in ('data-testid="tokens-section"', "createToken()", "revokeToken(t)",
              'data-testid="new-token"', '<option value="api"'):
        assert s in html, s
