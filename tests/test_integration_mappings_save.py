"""#247: Settings → Integrations → Save mappings always answered 500 (NameError: json).

app.py imports the module as ``_json``; the save and load paths used ``json``. The test runs
with a real metrics store, because the failure is on the store write — without a store the
endpoint skips it and passes."""
import ast
import pathlib

from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import app as app_module

APP = pathlib.Path(app_module.__file__)


def test_mappings_round_trip_with_a_store(tmp_path, monkeypatch):
    monkeypatch.setenv("METRICS_DB", str(tmp_path / "m.db"))
    from franklinwh_direct_connect_bridge import config, db
    monkeypatch.setattr(config, "_settings", None, raising=False)
    monkeypatch.setattr(db, "_store", None, raising=False)
    c = TestClient(app_module.create_app())
    want = [{"field": "soc", "protocol": "", "note": "test"}]
    r = c.put("/api/integrations", json={"mappings": want})
    assert r.status_code == 200, (r.status_code, r.text[:200])
    assert r.json()["count"] == 1
    got = c.get("/api/integrations")
    assert got.status_code == 200, got.text[:200]


def test_app_py_never_uses_a_bare_json_name():
    """The module is imported as _json; a bare ``json`` is a NameError at runtime."""
    tree = ast.parse(APP.read_text())
    bare = [n.lineno for n in ast.walk(tree)
            if isinstance(n, ast.Name) and n.id == "json" and isinstance(n.ctx, ast.Load)]
    assert bare == [], f"bare json used at lines {bare}"
