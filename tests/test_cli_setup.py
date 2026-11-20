"""`franklinwh-direct-connect-bridge setup` (pip and Docker): asks the aGate's address, the
ports, Security on or off and the first admin, saves them so a plain start needs no
variables, and never writes the password to a file. The run command's startup banner
shows the generated first-admin password only on the start that made it."""
from pathlib import Path

import pytest

from franklinwh_direct_connect_bridge import auth, cli, config, db, environment, security

pytestmark = pytest.mark.security_on


_REAL_CAN_LISTEN = cli._can_listen


def _answers(*replies):
    it = iter(replies)
    return lambda prompt="": next(it)


def _store():
    return db.get_store(config.get_settings())


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    monkeypatch.setattr(cli, "_probe", lambda host: (True, f"{host}: ok"))
    monkeypatch.setattr(cli, "_port_in_use", lambda port: False)
    monkeypatch.setattr(cli, "_can_listen", lambda host, port: True)   # a bridge may be running


def test_setup_saves_the_answers_and_makes_the_admin(capsys):
    rc = cli.main(["setup"], ask=_answers("10.0.0.5", "", "", "y", "y", "owner", "n"),
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
    cli.main(["setup"], ask=_answers("10.0.0.5", "", "", "y", "y", "", "n"),
             ask_secret=_answers(""))
    out = capsys.readouterr().out
    line = next(ln for ln in out.splitlines() if "Password:" in ln)
    pw = line.split("Password:")[1].split()[0]
    assert auth.authenticate(_store(), "admin", pw)
    assert pw not in (Path(environment.DATA_DIR) / "bridge.env").read_text()


def test_security_on_keeps_the_https_port_on():
    cli.main(["setup"], ask=_answers("10.0.0.5", "", "0", "y", "y", "", "n"),
             ask_secret=_answers(""))
    assert "HTTPS_PORT=8102" in (Path(environment.DATA_DIR) / "bridge.env").read_text()


def test_setup_with_security_off_makes_no_admin():
    cli.main(["setup"], ask=_answers("10.0.0.5", "", "", "n", "n"), ask_secret=_answers())
    st = _store()
    assert security.enabled(st) is False and not auth.has_admin(st)


def test_setup_turns_security_on_or_off_on_an_existing_install():
    st = _store()
    security.decide_install(st)
    st.set_config("install_date", "2026-01-01")
    auth.ensure_tables(st)
    auth.create_user(st, "owner", "a-long-password", "admin")
    cli.main(["setup"], ask=_answers("10.0.0.5", "", "", "n", "n"), ask_secret=_answers())
    assert security.enabled(st) is False
    cli.main(["setup"], ask=_answers("10.0.0.5", "", "", "y", "n"), ask_secret=_answers())
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


def test_enter_everywhere_accepts_the_defaults_and_leaves_the_admin_for_later(capsys):
    """Owner 2026-11-20: Enter takes every default; the admin is optional (the first start
    makes one and shows its password), and the output says what each answer means."""
    rc = cli.main(["setup"], ask=_answers("", "", "", "", "", "n"), ask_secret=_answers())
    assert rc == 0
    out = capsys.readouterr().out
    assert "Press Enter to accept" in out and "later" in out
    st = _store()
    assert security.enabled(st) is True and not auth.has_admin(st)
    assert "first start" in out


def test_setup_says_where_it_saves_and_stops_in_an_empty_folder_inside_data(
        capsys, monkeypatch, tmp_path):
    """Run from inside the data folder, ./data is a new, empty one: say so and stop,
    unless the owner says it's a new install."""
    (tmp_path / "data").mkdir()
    monkeypatch.chdir(tmp_path / "data")
    monkeypatch.setattr(environment, "DATA_DIR", "./data")
    rc = cli.main(["setup"], ask=_answers("n"), ask_secret=_answers())
    out = capsys.readouterr().out
    assert rc == 1 and "data/data" in out and "cd .." in out
    assert not (tmp_path / "data" / "data" / "bridge.env").exists()


def test_setup_offers_to_start_the_bridge(monkeypatch):
    started = []
    monkeypatch.setattr(cli, "serve", lambda s: started.append(s) or _done())
    monkeypatch.setattr(cli, "first_start_banner", lambda s: None)
    rc = cli.main(["setup"], ask=_answers("10.0.0.5", "", "", "n", ""), ask_secret=_answers())
    assert rc == 0 and len(started) == 1 and started[0].fwh_host == "10.0.0.5"


async def _done():
    return None


def test_with_security_off_the_banner_also_lists_the_https_address(capsys, monkeypatch):
    """Owner 2026-11-20 opened https://localhost:8102, which the banner didn't mention."""
    s = config.get_settings()
    monkeypatch.setattr(s, "security", "off")
    cli.first_start_banner(s)
    out = capsys.readouterr().out
    assert f"http://localhost:{s.http_port}" in out and f"https://localhost:{s.https_port}" in out


def test_setup_says_what_where_and_how_many_steps(capsys, monkeypatch):
    """Owner 2026-11-20: version, this folder, where it saves, prerequisites, step x of y."""
    from franklinwh_direct_connect_bridge import __version__
    cli.main(["setup"], ask=_answers("", "", "", "", "", "n"), ask_secret=_answers())
    out = capsys.readouterr().out
    assert __version__ in out and str(Path.cwd()) in out
    assert str(Path(environment.DATA_DIR).resolve()) in out and "bridge.env" in out
    assert "Python 3." in out and "new install" in out
    for n in (1, 2, 3, 4):
        assert f"Step {n} of 4" in out


def test_setup_warns_when_a_port_is_taken(capsys, monkeypatch):
    monkeypatch.setattr(cli, "_port_in_use", lambda port: port == 8101)
    cli.main(["setup"], ask=_answers("", "", "", "", "", "n"), ask_secret=_answers())
    out = capsys.readouterr().out
    assert "8101 is in use" in out and "Ctrl+C" in out


def test_stopping_with_ctrl_c_logs_no_https_error(caplog):
    import asyncio

    class _Server:
        config = type("C", (), {"port": 8102})

        async def serve(self):
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(cli.run_https(_Server()))
    assert "stopped" not in caplog.text


def test_setup_headings_stand_apart_and_say_when(capsys):
    """Owner 2026-11-20: a blank line before and after each heading, an underline, and the
    time."""
    import re
    cli.main(["setup"], ask=_answers("", "", "", "", "", "n"), ask_secret=_answers())
    lines = capsys.readouterr().out.splitlines()
    for n in (1, 2, 3, 4):
        i = next(k for k, ln in enumerate(lines) if ln.startswith(f"Step {n} of 4"))
        assert lines[i - 1] == "" and set(lines[i + 1]) == {"-"} and lines[i + 2] == ""
    assert any(re.search(r"20\d\d-\d\d-\d\d \d\d:\d\d", ln) for ln in lines[:8])


def test_the_startup_banner_says_when(capsys):
    import re
    cli.first_start_banner(config.get_settings())
    assert re.search(r"20\d\d-\d\d-\d\d \d\d:\d\d", capsys.readouterr().out)


def test_an_agate_that_does_not_answer_is_asked_again(capsys, monkeypatch):
    """Owner 2026-11-20: a wrong address is caught, not saved silently."""
    monkeypatch.setattr(cli, "_probe", lambda host: (host == "10.0.0.5", f"{host}: answer?"))
    cli.main(["setup"], ask=_answers("10.0.0.9", "n", "10.0.0.5", "", "", "", "", "n"),
             ask_secret=_answers())
    assert "FWH_HOST=10.0.0.5" in (Path(environment.DATA_DIR) / "bridge.env").read_text()
    cli.main(["setup"], ask=_answers("10.0.0.9", "y", "", "", "", "", "n"),
             ask_secret=_answers())      # kept on purpose (aGate off for now)
    assert "FWH_HOST=10.0.0.9" in (Path(environment.DATA_DIR) / "bridge.env").read_text()


def test_run_stops_before_starting_when_a_port_is_taken(capsys, monkeypatch):
    """Owner 2026-11-20: a taken port stopped the web app half-started. Now nothing starts."""
    import socket
    started = []
    monkeypatch.setattr(cli, "serve", lambda s: started.append(s))
    monkeypatch.setattr(cli, "_can_listen", _REAL_CAN_LISTEN)
    monkeypatch.setenv("HTTP_PORT", "0")
    with socket.socket() as busy:
        busy.bind(("0.0.0.0", 0))
        busy.listen()
        port = busy.getsockname()[1]
        monkeypatch.setenv("HTTPS_PORT", str(port))
        monkeypatch.setattr(config, "_settings", None)
        rc = cli.main(["run"])
    out = capsys.readouterr().out
    assert rc == 1 and not started
    assert f"Port {port} is in use" in out and "HTTPS_PORT" in out
