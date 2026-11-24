"""#87 / #155: wording left over from the old allow_writes gate and from HA before 2026.10.

- ``client.writes_enabled()`` always returns True, so no screen may tell the user to "enable
  writes (ALLOW_WRITES)": those checks can only fail while the page is still loading.
- The support bundle reports writes as the bridge applies them, not the inert option.
- HA 2026.10 calls add-ons Apps (Settings → Apps → App store); the install steps say so.
- The add-on's Watchdog switch is off after a fresh install; the docs say to turn it on.
- ``mqtt_enabled`` is on by default; the steps say to leave it on, not to enable it.
"""
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src/franklinwh_direct_connect_bridge"


def _ui_files():
    return sorted((SRC / "static/js").glob("*.js")) + sorted((SRC / "templates").rglob("*.html"))


@pytest.mark.parametrize("path", _ui_files(), ids=lambda p: p.name)
def test_no_screen_asks_for_allow_writes(path):
    src = path.read_text()
    assert "ALLOW_WRITES" not in src
    assert "Enable writes" not in src


def test_support_info_reports_writes_as_applied(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from franklinwh_direct_connect_bridge import app as app_module, config, db, environment
    from franklinwh_direct_connect_bridge.db import MetricsStore
    st = MetricsStore(str(tmp_path / "m.db"))
    monkeypatch.setattr(environment, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "_settings", None)
    monkeypatch.setenv("ALLOW_WRITES", "false")
    monkeypatch.setattr(db, "get_store", lambda s: st)
    c = TestClient(app_module.create_app())
    assert c.get("/api/support-info").json()["integration"]["writes_enabled"] is True


@pytest.mark.parametrize("doc", ["README.md", "INSTALL.md"])
def test_install_steps_use_the_apps_menu(doc):
    src = (ROOT / doc).read_text()
    assert "Settings → Apps → App store" in src
    # The old menu only as the note for earlier versions.
    assert src.count("Settings → Add-ons → Add-on Store") == src.count(
        "2026.10:\n   **Settings → Add-ons → Add-on Store**")


def test_readme_says_local_history_is_on_by_default():
    src = (ROOT / "README.md").read_text()
    assert "**off by default** in the add-on" not in src
    assert "all writes gated off until you enable them" not in src


@pytest.mark.parametrize("doc", ["README.md", "INSTALL.md", "DOCS.md"])
def test_docs_say_to_turn_the_watchdog_on(doc):
    src = (ROOT / doc).read_text()
    assert "turn on **Watchdog**" in src


@pytest.mark.parametrize("doc", ["README.md", "INSTALL.md"])
def test_mqtt_is_left_on_not_enabled(doc):
    src = (ROOT / doc).read_text()
    assert "enable\n   `mqtt_enabled`" not in src
    assert "Set `mqtt_enabled: true` to" not in src
    assert "`mqtt_enabled` on" in src


def test_guide_no_longer_says_install_md_lags():
    for name in ("installing.md", "quick-install.md"):
        src = (ROOT / "docs/guide" / name).read_text()
        assert "INSTALL.md still says" not in src
        assert "where INSTALL.md\nsays" not in src
