"""Legal-disclaimer modal endpoints — text, DB-persisted agreement, agreement logging."""

from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import app as app_module, db, logbuffer
from franklinwh_direct_connect_bridge.config import get_settings


def test_disclaimer_text_and_links():
    c = TestClient(app_module.create_app())
    d = c.get("/api/disclaimer").json()
    assert d["title"] and isinstance(d["lines"], list) and len(d["lines"]) >= 3
    assert "franklinwh-direct-connect-bridge" in d["issues_url"]
    # the published bridge guide, never the relative guide/ that 404s outside ingress (#231)
    assert d["docs_url"] == "https://david2069.github.io/franklinwh-direct-connect-bridge/guide/"
    assert d["agreed"] is False   # nobody has accepted on this installation yet


def test_disclaimer_ack_persists_and_gates(monkeypatch):
    c = TestClient(app_module.create_app())
    store = db.get_store(get_settings())          # tmp store (conftest-isolated)
    logbuffer.set_store(store)
    logbuffer.clear()
    cid = "client-abc"
    # unknown client -> not agreed -> modal would show
    assert c.get(f"/api/disclaimer?client_id={cid}").json()["agreed"] is False
    # agree
    r = c.post("/api/disclaimer/ack", json={"client_id": cid})
    assert r.status_code == 200 and r.json()["persisted"] is True
    # now the DB says agreed -> don't show again (survives localStorage clear)
    assert c.get(f"/api/disclaimer?client_id={cid}").json()["agreed"] is True
    assert store.disclaimer_agreed(cid) is True
    # the agreement was written to the durable log
    msgs = [e["message"] for e in store.logs(limit=50)]
    assert any("AGREED to the unofficial-app disclaimer" in m for m in msgs)


def test_one_acceptance_covers_the_installation():
    """#303: asked once per installation. Another browser, device or address, or a
    cleared browser storage (a new client id), is not asked again."""
    c = TestClient(app_module.create_app())
    db.get_store(get_settings())
    assert c.get("/api/disclaimer?client_id=phone").json()["agreed"] is False
    c.post("/api/disclaimer/ack", json={"client_id": "laptop"})
    assert c.get("/api/disclaimer?client_id=phone").json()["agreed"] is True
    assert c.get("/api/disclaimer").json()["agreed"] is True


def test_not_accepting_keeps_asking():
    """No ack is sent unless "I agree" is ticked, so a decline records nothing."""
    c = TestClient(app_module.create_app())
    db.get_store(get_settings())
    for _ in range(3):
        assert c.get("/api/disclaimer?client_id=phone").json()["agreed"] is False
