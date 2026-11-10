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
        # No gateway to name: device reads are refused (#379), before any connection.
        assert c.get("/api/summary").status_code == 400
        assert c.get("/api/site/timezone").status_code == 400
    finally:
        logging.getLogger("franklinwh_direct_connect_api").removeHandler(h)
    assert not [m for m in seen if "connect to" in m], seen
