"""#409: the install smoke check (tools/install_smoke.py) and its workflow. The checks run in
CI against a real install; these pin the parts that decide pass or fail."""
import importlib.util
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("install_smoke", ROOT / "tools/install_smoke.py")
smoke = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(smoke)


def test_errors_and_tracebacks_fail_the_log():
    log = ("2026-10-31 INFO poller: started\n"
           "2026-10-31 ERROR mqtt: connect refused\n"
           "Traceback (most recent call last):\n"
           "2026-10-31 INFO an error count of 0\n")
    assert smoke.bad_log_lines(log) == ["2026-10-31 ERROR mqtt: connect refused",
                                        "Traceback (most recent call last):"]


def test_only_this_gateways_discovery_configs_count():
    topics = ["homeassistant/sensor/fhp0012345678/soc/config",
              "homeassistant/sensor/fhp0012345678/soc/state",
              "homeassistant/sensor/fhp0099999999/soc/config",
              "franklinwh-local/fhp0012345678/soc/config"]
    assert smoke.discovery_topics(topics, "FHP0012345678", "homeassistant") == [
        "homeassistant/sensor/fhp0012345678/soc/config"]
    assert smoke.discovery_topics(topics, "", "homeassistant") == []


def test_the_workflow_runs_the_four_shared_jobs():
    wf = (ROOT / ".github/workflows/install-smoke.yml").read_text()
    assert sorted(re.findall(r"name: ([a-z]+-n?o?mqtt),", wf)) == [
        "docker-mqtt", "docker-nomqtt", "python-mqtt", "python-nomqtt"]
    assert "tools/install_smoke.py" in wf
