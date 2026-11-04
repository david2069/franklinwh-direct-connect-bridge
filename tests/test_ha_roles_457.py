"""#457 phase 3b: Home Assistant sidebar users get the role of their HA group."""
import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import app as app_module, auth, db, environment, security, tls
from franklinwh_direct_connect_bridge.db import MetricsStore

pytestmark = pytest.mark.security_on
ING = {"X-Ingress-Path": "/api/hassio_ingress/x", "X-Remote-User-Name": "dana"}


@pytest.mark.parametrize("groups,on,role", [
    ("system-admin", True, "admin"), ("system-admin", False, "admin"),
    ("system-users", True, "user"), ("system-users", False, "user"),
    ("system-read-only", True, "viewer"), ("system-read-only", False, "viewer"),
    ("system-users,system-admin", True, "admin"),          # the strongest group wins
    ("some-custom-group", True, "user"),
    (None, True, "user"),          # an older Supervisor sends no groups: least access when on
    (None, False, "admin"),        # ... and as before while Security is off
])
def test_the_ha_group_decides_the_role(groups, on, role):
    h = dict(ING, **({"X-Remote-User-Groups": groups} if groups else {}))
    p = security.ingress_principal(h, on)
    assert p["role"] == role and p["username"] == "dana" and p["via"] == "ingress"
    assert p["groups_known"] is bool(groups)


@pytest.fixture
def client(tmp_path, monkeypatch):
    store = MetricsStore(str(tmp_path / "m.db"))
    monkeypatch.setattr(db, "get_store", lambda s: store)
    monkeypatch.setattr(environment, "IS_HA_ADDON", True)
    monkeypatch.setattr(tls, "running", lambda: True)
    app = app_module.create_app()
    c = TestClient(app, client=("172.30.32.2", 5000))
    c.store = store
    return c


@pytest.mark.parametrize("on", [True, False])
def test_roles_apply_in_the_sidebar_with_security_on_or_off(client, on):
    security.set_enabled(client.store, on)
    viewer = dict(ING, **{"X-Remote-User-Groups": "system-read-only"})
    user = dict(ING, **{"X-Remote-User-Groups": "system-users"})
    admin = dict(ING, **{"X-Remote-User-Groups": "system-admin"})
    assert client.put("/api/settings", json={}, headers=viewer).status_code == 403
    assert client.post("/api/mode", json={}, headers=viewer).status_code == 403
    assert client.get("/api/summary", headers=viewer).status_code != 403
    assert client.post("/api/mode", json={}, headers=user).status_code != 403
    r = client.put("/api/settings", json={}, headers=user)
    assert r.status_code == 403 and r.json()["detail"] == "Your role (user) can't do this."
    assert client.put("/api/settings", json={}, headers=admin).status_code != 403
    me = client.get("/api/auth/me", headers=user).json()["principal"]
    assert me == {"username": "dana", "role": "user", "via": "ingress", "groups_known": True}


def test_an_old_supervisor_admin_can_still_add_the_first_account(client):
    """No groups sent and Security off (an upgrade): the sidebar stays admin, so the
    first admin account can be made there."""
    security.set_enabled(client.store, False)
    auth._exec(client.store, "DELETE FROM auth_users")
    r = client.post("/api/security/users", json={"username": "boss", "password": "long enough",
                                                  "role": "admin"}, headers=ING)
    assert r.status_code == 200


def test_the_add_on_lets_every_ha_user_open_the_panel():
    from pathlib import Path
    root = Path(app_module.__file__).resolve().parents[2]
    assert "panel_admin: false" in (root / "config.yaml").read_text()
    html = (Path(app_module.__file__).parent / "templates/tabs/settings.html").read_text()
    assert 'data-testid="ha-groups-unknown"' in html and "2026.10.4" in html
