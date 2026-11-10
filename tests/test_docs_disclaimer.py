"""The docs site's first page carries the in-app disclaimer verbatim, and the full terms.

docs/index.md copies the five ``lines`` of GET /api/disclaimer (api_disclaimer() in
app.py) word for word. If either side changes, this fails, so the published disclaimer
cannot quietly drift from the one the app shows. The full terms are included from
LICENSE at build time, so only the include itself is checked here.
"""
from pathlib import Path

from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import app as app_module

DOCS_INDEX = Path(__file__).resolve().parents[1] / "docs" / "index.md"


def test_docs_index_contains_each_disclaimer_line_verbatim():
    lines = TestClient(app_module.create_app()).get("/api/disclaimer").json()["lines"]
    assert len(lines) == 5
    page = DOCS_INDEX.read_text(encoding="utf-8")
    missing = [line for line in lines if line not in page]
    assert not missing, f"docs/index.md no longer contains these disclaimer lines: {missing}"


def test_docs_index_includes_full_terms_from_license():
    page = DOCS_INDEX.read_text(encoding="utf-8")
    assert '--8<-- "LICENSE"' in page
