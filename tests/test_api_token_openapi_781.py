"""#781: an api account's token can read the API schema (/openapi.json), which the role
meant for integrations needs to discover the API. /docs and /redoc stay web pages."""
from test_api_tokens_457 import app, https, store  # noqa: F401 — fixtures
import pytest

from franklinwh_direct_connect_bridge import auth, security

pytestmark = pytest.mark.security_on


def test_the_schema_is_readable_by_every_role():
    assert set(security.required("GET", "/openapi.json")) == {"admin", "user", "viewer", "api"}


def test_the_doc_pages_stay_pages():
    for p in ("/docs", "/redoc"):
        assert set(security.required("GET", p)) == {"admin", "user", "viewer"}


def test_an_api_token_gets_the_schema(app, store):  # noqa: F811
    u = auth.create_user(store, "ha-rest", None, "api")
    tok, _ = auth.create_token(store, u["id"], "rest", 365)
    c = https(app, tok)
    r = c.get("/openapi.json")
    assert r.status_code == 200 and "paths" in r.json()
    assert c.get("/docs").status_code == 403
