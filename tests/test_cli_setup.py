"""`franklinwh-direct-connect-bridge setup` (pip and Docker): asks the aGate's address, the
ports, Security on or off and the first admin, saves them so a plain start needs no
variables, and never writes the password to a file. The run command's startup banner
shows the generated first-admin password only on the start that made it."""
from pathlib import Path

import pytest

from franklinwh_direct_connect_bridge import auth, cli, config, db, environment, security

pytestmark = pytest.mark.security_on


def _answers(*replies):
    it = iter(replies)
    return lambda prompt="": next(it)


def _store():
    return db.get_store(config.get_settings())


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    monkeypatch.setattr(cli, "_probe_line", lambda host: f"{host}: ok")


def test_setup_saves_the_answers_and_makes_the_admin(capsys):
    rc = cli.main(["setup"], ask=_answers("10.0.0.5", "", "", "y", "owner"),
                  ask_secret=_answers("a-long-password", "a-long-password"))
    assert rc == 0
    text = (Path(environment.DATA_DIR) / "bridge.env").read_text()
    assert "FWH_HOST=10.0.0.5" in text and "HTTP_PORT=8101" in text
    assert "a-long-password" not in text and "PASSWORD" not in text
    st = _store()
    assert security.enabled(st) is True
    assert auth.authenticate(st, "owner", "a-long-password")
    assert "a-long-password" not in capsys.readouterr().out


def test_setup_generates_a_password_when_left_blank(capsys):
    cli.main(["setup"], ask=_answers("10.0.0.5", "", "", "y", ""),
             ask_secret=_answers(""))
    out = capsys.readouterr().out
    line = next(ln for ln in out.splitlines() if "Password:" in ln)
    pw = line.split("Password:")[1].split()[0]
    assert auth.authenticate(_store(), "admin", pw)
    assert pw not in (Path(environment.DATA_DIR) / "bridge.env").read_text()


def test_security_on_keeps_the_https_port_on():
    cli.main(["setup"], ask=_answers("10.0.0.5", "", "0", "y", ""),
             ask_secret=_answers(""))
    assert "HTTPS_PORT=8102" in (Path(environment.DATA_DIR) / "bridge.env").read_text()


def test_setup_with_security_off_makes_no_admin():
    cli.main(["setup"], ask=_answers("10.0.0.5", "", "", "n"), ask_secret=_answers())
    st = _store()
    assert security.enabled(st) is False and not auth.has_admin(st)


def test_setup_turns_security_on_or_off_on_an_existing_install():
    st = _store()
    security.decide_install(st)
    st.set_config("install_date", "2026-01-01")
    auth.ensure_tables(st)
    auth.create_user(st, "owner", "a-long-password", "admin")
    cli.main(["setup"], ask=_answers("10.0.0.5", "", "", "n"), ask_secret=_answers())
    assert security.enabled(st) is False
    cli.main(["setup"], ask=_answers("10.0.0.5", "", "", "y"), ask_secret=_answers())
    assert security.enabled(st) is True
    assert [u["username"] for u in auth.users(st)] == ["owner"]   # kept, none added


def test_the_saved_file_is_read_and_the_environment_wins(monkeypatch):
    (Path(environment.DATA_DIR) / "bridge.env").write_text("FWH_HOST=10.0.0.5\nHTTP_PORT=9101\n")
    s = config.load_settings()
    assert s.fwh_host == "10.0.0.5" and s.http_port == 9101
    monkeypatch.setenv("HTTP_PORT", "8111")
    assert config.load_settings().http_port == 8111


def test_the_banner_shows_a_generated_password_once(capsys):
    s = config.get_settings()
    cli.first_start_banner(s)
    out = capsys.readouterr().out
    assert "Security: on" in out and "Username: admin" in out and "Password:" in out
    cli.first_start_banner(s)
    out = capsys.readouterr().out
    assert "Password:" not in out and "reset-password" in out


def test_the_banner_says_when_security_is_off(capsys, monkeypatch):
    s = config.get_settings()
    monkeypatch.setattr(s, "security", "off")
    cli.first_start_banner(s)
    out = capsys.readouterr().out
    assert "Security: off" in out and "Password:" not in out
