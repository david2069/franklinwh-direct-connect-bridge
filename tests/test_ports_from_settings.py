"""No port is typed into the UI (owner, 2026-11-11): the Direct Connect port comes from
``fwh_port`` and the Modbus TCP Server port from ``modbus_port`` (or the Control tab's
override), with 9000 and 502 only as those settings' defaults."""
import re
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1] / "src/franklinwh_direct_connect_bridge"

# A port typed as UI text: ":9000", "TCP 502", "port 502", "9000 open", "port: 9000" …
LITERAL = re.compile(r"(:\s?|TCP |[Pp]ort |SunSpec )(9000|502)\b|\b(9000|502) open|\|\| ?(9000|502)\b"
                     r"|placeholder=\"(9000|502)\"|!== ?9000")


def _strip_comments(f):
    t = f.read_text()
    t = re.sub(r"<!--.*?-->", lambda m: "\n" * m.group().count("\n"), t, flags=re.S)
    if f.suffix == ".js":
        t = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group().count("\n"), t, flags=re.S)
        t = re.sub(r"(^|\s)//.*", "", t, flags=re.M)
    return t


def _ui_files():
    yield from (ROOT / "templates").rglob("*.html")
    yield from (ROOT / "static/js").glob("*.js")


def test_no_port_is_typed_into_the_ui():
    hits = []
    for f in _ui_files():
        for n, line in enumerate(_strip_comments(f).splitlines(), 1):
            if LITERAL.search(line):
                hits.append(f"{f.relative_to(ROOT)}:{n}: {line.strip()[:100]}")
    assert not hits, "\n".join(hits)


def test_the_page_gets_the_ports_from_the_settings(monkeypatch, tmp_path):
    from franklinwh_direct_connect_bridge import app as app_module, config, environment
    monkeypatch.setattr(environment, "DATA_DIR", str(tmp_path))
    monkeypatch.setenv("FWH_PORT", "19000")
    monkeypatch.setenv("MODBUS_PORT", "1502")
    monkeypatch.setattr(config, "_settings", None)
    html = TestClient(app_module.create_app()).get("/").text
    assert '"dc": 19000' in html and '"modbus": 1502' in html


def test_modbus_port_setting_is_the_default_target(monkeypatch):
    from franklinwh_direct_connect_bridge import battery_control as bc, config
    monkeypatch.setenv("MODBUS_PORT", "1502")
    monkeypatch.setattr(config, "_settings", None)
    bc.set_host_override("")
    assert bc.effective_target("10.0.0.5") == ("10.0.0.5", 1502)
    bc.set_host_override("10.0.0.9", 2502)            # the Control tab's override still wins
    try:
        assert bc.effective_target("10.0.0.5") == ("10.0.0.9", 2502)
    finally:
        bc.set_host_override("")
    monkeypatch.delenv("MODBUS_PORT")
    monkeypatch.setattr(config, "_settings", None)
    assert bc.effective_target("10.0.0.5") == ("10.0.0.5", 502)
