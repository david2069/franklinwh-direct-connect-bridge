"""Facts the README and API comparison state that the code can check."""
import pathlib
import re

from franklinwh_direct_connect_bridge import app as app_module

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_the_readme_names_the_real_add_on_slug():
    slug = re.search(r'^slug:\s*"?([\w-]+)', (ROOT / "config.yaml").read_text(), re.M)[1]
    said = re.search(r"add-on slug is still\s*\n>\s*`([\w-]+)`", (ROOT / "README.md").read_text())[1]
    assert said == slug


def test_the_docs_count_the_real_cmd_routes():
    n = sum(1 for r in app_module.create_app().routes
            if getattr(r, "path", "").startswith("/api/cmd/"))
    assert f"| `/api/cmd/*` | {n} |" in (ROOT / "README.md").read_text()
    assert f"**{n} `/api/cmd/*` live" in (ROOT / "docs/API_COMPARISON.md").read_text()


def test_the_editable_install_names_the_library_checkout():
    for doc in ("README.md", "INSTALL.md"):
        text = (ROOT / doc).read_text()
        assert "pip install -e ../franklinwh-direct-connect-api" in text
        assert "../franklinwh-local " not in text
