"""The generated first-admin password (Docker and pip) goes to the console only: never to
the stored Bridge log (Logs tab, support bundle), and an older stored copy is masked."""
import logging

import pytest

from franklinwh_direct_connect_bridge import auth, logbuffer
from franklinwh_direct_connect_bridge.config import Settings
from franklinwh_direct_connect_bridge.db import MetricsStore

pytestmark = pytest.mark.security_on


@pytest.fixture
def store(tmp_path):
    st = MetricsStore(str(tmp_path / "p.db"))
    auth.ensure_tables(st)
    logbuffer.install()
    logbuffer.set_store(st)
    yield st
    logbuffer.set_store(None)


def _stored(st):
    return [r[0] for r in st._conn.execute("SELECT message FROM app_logs")]


def test_the_generated_password_is_printed_but_not_stored(store, caplog):
    caplog.set_level(logging.WARNING)
    assert auth.ensure_first_admin(store, Settings(), on_addon=False,
                                   security_on=True) == "generated"
    printed = [r.getMessage() for r in caplog.records if "Password:" in r.getMessage()]
    assert len(printed) == 1                                  # the console still shows it
    pw = printed[0].split("Password: ")[1].split()[0]
    stored = _stored(store)
    assert not any(pw in m for m in stored)
    assert not any(pw in e["message"] for e in logbuffer.get_logs(limit=500))
    assert any("first admin 'admin' created" in m and "console" in m for m in stored)


def test_an_older_stored_password_line_is_masked(tmp_path):
    st = MetricsStore(str(tmp_path / "o.db"))
    st.log_line(1.0, "WARNING", 30, "franklinwh_direct_connect_bridge.auth",
                "Security: first admin created. Username: admin  Password: s3cretXYZ  "
                "(shown once; change it under Settings → Admin → Security)")
    st.close()
    st = MetricsStore(str(tmp_path / "o.db"))
    (m,) = _stored(st)
    assert "s3cretXYZ" not in m and "Password: ********" in m
