"""Global test isolation.

A test once truncated the live bridge's log file because it logged + called
``logbuffer.clear()`` WITHOUT redirecting ``DATA_DIR`` — and docker-compose mounts
``./data:/data``, so the host default ``./data`` IS the running bridge's data dir.
This autouse fixture makes that impossible: every test gets a fresh tmp ``DATA_DIR``
and a settings singleton pinned to a tmp ``metrics_db`` (its default is an absolute
``/data/metrics.db``), and the store cache + log buffer are reset around each test.

A test that specifically needs the real defaults can opt out with
``@pytest.mark.real_data_dir``.
"""

import pytest

from franklinwh_direct_connect_bridge import environment, config, db, logbuffer


def pytest_configure(config):  # noqa: ARG001 — pytest hook
    config.addinivalue_line("markers",
                            "real_data_dir: run without the tmp DATA_DIR isolation")


@pytest.fixture(autouse=True)
def _isolate_data_dir(request, tmp_path, monkeypatch):
    if request.node.get_closest_marker("real_data_dir"):
        yield
        return
    monkeypatch.setattr(environment, "DATA_DIR", str(tmp_path))
    # Pin settings to a tmp metrics DB — the default is an absolute /data/metrics.db, so
    # DATA_DIR alone would not stop a store from opening the real (mounted) database.
    monkeypatch.setattr(config, "_settings", None)
    s = config.get_settings()
    monkeypatch.setattr(s, "metrics_db", str(tmp_path / "metrics.db"))
    monkeypatch.setattr(config, "_settings", s)
    db.reset_store()
    logbuffer.set_store(None)
    logbuffer.clear()
    yield
    db.reset_store()
    logbuffer.set_store(None)
