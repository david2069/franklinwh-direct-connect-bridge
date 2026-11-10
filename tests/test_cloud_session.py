"""#233 / #248: the cloud status loop logs in once, backs off on failure, and never guesses an aGate.

The library's network edges (PasswordAuth's login, the Client's HTTP calls) are replaced
with fakes; the bridge code under test is real."""
import pytest

pytest.importorskip("franklinwh_cloud")
import franklinwh_cloud.auth as fauth  # noqa: E402
import franklinwh_cloud.client as fclient  # noqa: E402
import franklinwh_cloud.wrapper as fwrapper  # noqa: E402

from franklinwh_direct_connect_bridge import cloud_status as cs  # noqa: E402


class _Auth:
    logins = 0

    def __init__(self, email, password, *a, **kw):
        self.email, self.password, self.info = email, password, None

    async def get_token(self, force_refresh=False):
        if self.info and not force_refresh:
            return self.info["token"]
        _Auth.logins += 1
        if self.password == "wrong":
            raise RuntimeError("401 invalid credentials")
        self.info = {"token": "t"}
        return "t"


class _Audit:
    rows: list = []


class _Stats:
    class current:
        run_status, tou_mode, effective_mode, run_status_desc = 0, 0, "Self", ""


class _Client:
    gateways = ["10060006A02F00000001"]
    bound: list = []

    closed = 0

    def __init__(self, auth, gateway, **kw):
        self.auth, self.gateway, self.session = auth, gateway, None
        _Client.bound.append(gateway)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        _Client.closed += 1
        return False

    async def get_home_gateway_list(self):
        return {"result": [{"id": g} for g in _Client.gateways]}

    async def get_stats(self, **kw):
        assert self.gateway != "placeholder", "a gateway call on the placeholder"
        return _Stats()

    async def get_programme_info(self):
        return []

    def get_metrics(self):
        return {}


@pytest.fixture(autouse=True)
def fakes(monkeypatch):
    _Auth.logins = 0
    _Client.gateways = ["10060006A02F00000001"]
    _Client.bound = []
    _Client.closed = 0
    monkeypatch.setattr(fauth, "PasswordAuth", _Auth)
    monkeypatch.setattr(fclient, "Client", _Client)
    # The library's facade imports both by name; patch it too, so no test reaches the network.
    monkeypatch.setattr(fwrapper, "PasswordAuth", _Auth)
    monkeypatch.setattr(fwrapper, "Client", _Client)
    monkeypatch.setattr(cs, "_AUTH", {}, raising=False)
    monkeypatch.setattr(cs, "_SERIAL", {}, raising=False)
    from franklinwh_direct_connect_bridge import config, providers
    store: dict = {}
    monkeypatch.setattr(config, "load_overrides", lambda: dict(store))
    monkeypatch.setattr(config, "save_override_raw", lambda k, v: store.__setitem__(k, v))
    monkeypatch.setattr(providers, "_hold", {"active": False, "message": "", "since": 0.0,
                                             "account": ""}, raising=False)
    monkeypatch.setattr(providers, "_hold_loaded", True, raising=False)
    audit: list = []
    monkeypatch.setattr(providers, "AUDIT", lambda action, **kw: audit.append((action, kw)),
                        raising=False)
    _Audit.rows = audit


# -- #233: one login, many passes ---------------------------------------------------------
def test_twelve_passes_make_one_login():
    for _ in range(12):
        cs._read_sync("a@example.com", "pw", "10060006a02f00000001")
    assert _Auth.logins == 1
    # The account's aGates are listed once per login, not once per pass.
    assert _Client.bound.count("placeholder") == 1
    assert set(_Client.bound) == {"placeholder", "10060006A02F00000001"}


def test_new_credentials_log_in_again():
    cs._read_sync("a@example.com", "pw", None)
    cs._read_sync("a@example.com", "pw2", None)
    assert _Auth.logins == 2


@pytest.mark.parametrize("fails,want", [(1, 600), (2, 1200), (3, 1800), (9, 1800)])
def test_failed_passes_back_off_and_never_beat_the_interval(fails, want):
    assert cs.retry_delay(300, fails) == want
    assert cs.retry_delay(300, fails) >= 300


def test_the_45s_retry_is_gone():
    import pathlib
    src = pathlib.Path(cs.__file__).with_name("app.py").read_text()
    assert "min(interval, 45)" not in src
    assert "cloud_status.retry_delay(interval, _fail_streak)" in src


# -- #248: the serial ---------------------------------------------------------------------
def test_no_serial_and_one_agate_uses_it():
    cs._read_sync("a@example.com", "pw", None)
    assert _Client.bound[-1] == "10060006A02F00000001"


def test_no_serial_and_several_agates_never_guesses():
    from franklinwh_cloud.exceptions import GatewaySelectionError
    _Client.gateways = ["SN1", "SN2"]
    with pytest.raises(GatewaySelectionError) as e:
        cs._read_sync("a@example.com", "pw", None)
    assert e.value.serials == ["SN1", "SN2"]
    assert _Client.bound == ["placeholder"]                     # only the account-level list


def test_verify_settles_the_serial():
    _Client.gateways = ["SN1"]
    assert cs.verify_credentials("a@example.com", "pw")["gateway"] == "SN1"
    _Client.gateways = ["SN1", "SN2"]
    v = cs.verify_credentials("a@example.com", "pw")
    assert v["ok"] is False and "SN1" in v["detail"] and "SN2" in v["detail"]
    v = cs.verify_credentials("a@example.com", "pw", "sn2")
    assert v["ok"] is True and v["gateway"] == "SN2"
    v = cs.verify_credentials("a@example.com", "pw", "SN9")
    assert v["ok"] is False and "not on this account" in v["detail"]


def test_verify_reports_a_bad_password():
    v = cs.verify_credentials("a@example.com", "wrong")
    assert v["ok"] is False and v["rejected"] is True


def test_the_status_loop_waits_for_credentials_instead_of_exiting():
    """#248: credentials saved from Settings must start cloud polling without an add-on
    restart. The loop used to `return` when it started with none, and never came back."""
    import pathlib
    src = pathlib.Path(cs.__file__).with_name("app.py").read_text()
    body = src[src.index("def _cloud_status_loop():"):]
    head = body[:body.index("FWH_CLOUD_STATUS")]
    assert "while True:" in head and "_t.sleep(_CLOUD_CREDS_WAIT_S)" in head
    assert "return" not in head



# -- 2026-10-21: one FranklinWH rejection puts the whole account on hold ------------------
class AccountLockedException(Exception):
    pass


def _reject_with(monkeypatch, msg):
    async def _no(self, force_refresh=False):
        _Auth.logins += 1
        raise AccountLockedException(msg)
    monkeypatch.setattr(_Auth, "get_token", _no)


def test_a_rejection_holds_every_later_login_whatever_is_typed(monkeypatch):
    from franklinwh_direct_connect_bridge import providers
    _reject_with(monkeypatch, "Incorrect password, you still have 2 chances to enter.")
    v = cs.verify_credentials("David@example.com", "pw")
    assert v["ok"] is False and v["held"] is True
    assert "Incorrect password, you still have 2 chances to enter." in v["detail"]  # verbatim
    sent = _Auth.logins
    # The 2026-10-21 bypass: change the email's case, add a serial, change the password.
    for email, pw, gw in [("david@example.com", "pw", None), ("david@example.com", "pw2", "SN1")]:
        v = cs.verify_credentials(email, pw, gw)
        assert v["ok"] is False and v["held"] is True and "on hold" in v["detail"]
    with pytest.raises(providers.CloudLoginHeld):
        cs._read_sync("david@example.com", "pw", "SN1")
    assert _Auth.logins == sent, "a login was sent while the hold was on"


def test_saving_new_credentials_does_not_clear_the_hold(monkeypatch):
    from franklinwh_direct_connect_bridge import providers
    _reject_with(monkeypatch, "The password is locked. Please try again after 2 min 38 sec")
    cs.verify_credentials("a@example.com", "pw")
    providers.reset_cloud_breaker()                 # what a credential change calls
    assert providers.cloud_hold()["active"] is True


def test_only_an_explicit_clear_lifts_the_hold(monkeypatch):
    from franklinwh_direct_connect_bridge import providers
    _reject_with(monkeypatch, "Incorrect password, you still have 1 chances to enter.")
    cs.verify_credentials("a@example.com", "pw")
    providers.clear_cloud_hold("test")
    monkeypatch.setattr(_Auth, "get_token", _Auth.get_token.__wrapped__
                        if hasattr(_Auth.get_token, "__wrapped__") else _Auth.get_token)
    assert providers.cloud_hold()["active"] is False


def test_every_login_attempt_is_audited_with_the_exact_reply_and_no_secret(monkeypatch):
    _reject_with(monkeypatch, "Incorrect password, you still have 2 chances to enter.")
    cs.verify_credentials("david@example.com", "s3cret-pw", None)
    text = repr(_Audit.rows)
    assert "cloud_login" in text and "cloud_login_hold" in text
    assert "Incorrect password, you still have 2 chances to enter." in text
    assert "d***@example.com" in text
    assert "s3cret-pw" not in text and "david@example.com" not in text


def test_a_successful_login_is_audited_too():
    cs.verify_credentials("a@example.com", "pw", "SN1")
    assert any(a == "cloud_login" and kw.get("result") == "ok" for a, kw in _Audit.rows)


def test_the_card_shows_the_hold_and_offers_an_explicit_clear():
    import pathlib
    root = pathlib.Path(cs.__file__).parent
    js = (root / "static/js/settings_tab.js").read_text()
    html = (root / "templates/tabs/settings.html").read_text()
    assert "get cloudBlocked() { return !!this.cfg?.cloud?.hold?.active; }" in js
    assert "api/cloud/hold/clear" in js and "clearCloudHold()" in html
    assert "cfg.cloud?.hold?.message" in html
    import re
    card = html[html.index("FranklinWH Cloud API"):html.index("Integration → Mapping")]
    card = re.sub(r"<!--.*?-->", "", card, flags=re.S)       # judge markup, not comments
    assert "text-right" not in card, "cloud card fields must be left-aligned"
    # Not a password input: Safari autofilled one, and generated a "Strong Password" into
    # autocomplete=new-password, both spending FranklinWH lockout attempts (2026-10-21).
    assert 'type="password"' not in card and "new-password" not in card
    assert 'x-model="form.fwh_cloud_password"' in card and 'autocomplete="off"' in card
    assert "-webkit-text-security:disc" in card and "Don't use a password the browser suggests" in card



def test_every_pass_closes_its_client_session():
    for _ in range(3):
        cs._read_sync("a@example.com", "pw", None)
    assert _Client.closed >= 3          # the library closes the gateway-list client too


def test_rate_limiting_never_holds_the_account(monkeypatch):
    """franklinwh-cloud 0.6.0: RateLimitedError (HTTP/code 429) is not a rejected password."""
    from franklinwh_cloud.exceptions import RateLimitedError
    from franklinwh_direct_connect_bridge import providers

    async def _limited(self, force_refresh=False):
        raise RateLimitedError("Too Many Requests")
    monkeypatch.setattr(_Auth, "get_token", _limited)
    v = cs.verify_credentials("a@example.com", "pw")
    assert v["ok"] is False and v["held"] is False
    assert providers.cloud_hold()["active"] is False


def test_an_unknown_login_refusal_also_holds(monkeypatch):
    """0.6.0's LoginError (unknown code / no account in the reply) is still a refusal."""
    from franklinwh_cloud.exceptions import LoginError
    from franklinwh_direct_connect_bridge import providers

    async def _refused(self, force_refresh=False):
        raise LoginError("refused")
    monkeypatch.setattr(_Auth, "get_token", _refused)
    assert cs.verify_credentials("a@example.com", "pw")["held"] is True
    assert providers.cloud_hold()["active"] is True
