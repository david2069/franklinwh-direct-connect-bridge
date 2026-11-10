"""#410: the store lives under DATA_DIR, so a pip install (DATA_DIR ./data) starts on a host
with no writable /data, while the add-on and Docker keep /data/metrics.db."""
from franklinwh_direct_connect_bridge import config, environment


def test_a_pip_install_keeps_its_store_under_its_own_data_dir(monkeypatch):
    monkeypatch.setattr(environment, "DATA_DIR", "./data")
    monkeypatch.delenv("METRICS_DB", raising=False)
    assert config.Settings().metrics_db == "data/metrics.db"


def test_the_add_on_and_docker_keep_data_metrics_db(monkeypatch):
    monkeypatch.setattr(environment, "DATA_DIR", "/data")
    monkeypatch.delenv("METRICS_DB", raising=False)
    assert config.Settings().metrics_db == "/data/metrics.db"


def test_an_explicit_metrics_db_still_wins(monkeypatch):
    monkeypatch.setattr(environment, "DATA_DIR", "./data")
    monkeypatch.setenv("METRICS_DB", "/srv/fwh/metrics.db")
    assert config.Settings().metrics_db == "/srv/fwh/metrics.db"
