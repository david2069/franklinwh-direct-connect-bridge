"""Sign-in and accounts are set up one of two ways, never mixed (owner 2026-11-20): the
Home Assistant add-on way or the standalone (Docker and pip) way. One table says which
features belong to which; the checks read it."""
from test_api_tokens_457 import app, https, store  # noqa: F401 — fixtures
import pytest

from franklinwh_direct_connect_bridge import auth, cli, config, environment

pytestmark = pytest.mark.security_on


def test_the_two_ways_share_no_feature():
    ha = set(environment.ACCOUNT_FEATURES[environment.ACCOUNTS_HA])
    sa = set(environment.ACCOUNT_FEATURES[environment.ACCOUNTS_STANDALONE])
    assert ha and sa and not ha & sa
    assert "custom_roles" in sa and "ha_users" in ha


@pytest.mark.parametrize("addon,mode", [(True, "home_assistant"), (False, "standalone")])
def test_the_mode_follows_the_runtime(monkeypatch, addon, mode):
    monkeypatch.setattr(environment, "IS_HA_ADDON", addon)
    assert environment.accounts_mode() == mode
    assert environment.account_feature("custom_roles") is (not addon)
    assert environment.account_feature("ha_users") is addon


def test_an_unknown_feature_is_an_error():
    with pytest.raises(KeyError):
        environment.account_feature("no_such_thing")


def test_the_add_on_reads_no_settings_file_and_has_no_setup(monkeypatch, tmp_path):
    (tmp_path / "bridge.env").write_text("HTTP_PORT=9101\n")
    monkeypatch.setattr(environment, "IS_HA_ADDON", True)
    assert config.load_settings().http_port == 8101
    assert cli.main(["setup"], ask=lambda p="": "", ask_secret=lambda p="": "") == 2


def test_the_add_on_makes_no_first_admin_from_settings(monkeypatch):
    from franklinwh_direct_connect_bridge import db
    monkeypatch.setattr(environment, "IS_HA_ADDON", True)
    s = config.get_settings()
    monkeypatch.setattr(s, "admin_username", "owner")
    monkeypatch.setattr(s, "admin_password", "a-long-password")
    st = db.get_store(s)
    auth.ensure_tables(st)
    assert auth.ensure_first_admin(st, s, security_on=True) is None
    assert not auth.has_admin(st)


def test_the_security_api_says_which_way(app, store):  # noqa: F811
    u = auth.create_user(store, "owner", None, "api")
    tok, _ = auth.create_token(store, u["id"], "t", 30)
    d = https(app, tok).get("/api/security").json()
    assert d["accounts_mode"] == "standalone"
    assert "custom_roles" in d["account_features"]
