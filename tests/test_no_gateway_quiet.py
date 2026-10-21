"""#265: before any gateway exists, the first page load makes no device connection."""

import logging

from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import app as app_module, config


def test_no_gateway_means_no_connect_attempt(monkeypatch):
    monkeypatch.setattr(config.get_settings(), "fwh_host", "")
    seen = []

    class H(logging.Handler):
        def emit(self, r):
            seen.append(r.getMessage())

    h = H()
    logging.getLogger("franklinwh_direct_connect_api").addHandler(h)
    try:
        c = TestClient(app_module.create_app())
        assert c.get("/api/gateways").json() == []
        s = c.get("/api/summary").json()
        assert s["ok"] is False and s["error"] == "no gateway configured"
        assert c.get("/api/site/timezone").json() == {"available": False}
    finally:
        logging.getLogger("franklinwh_direct_connect_api").removeHandler(h)
    assert not [m for m in seen if "connect to" in m], seen
