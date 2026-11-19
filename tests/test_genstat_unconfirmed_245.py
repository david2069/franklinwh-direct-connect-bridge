"""#245: on the reference aGate genStat reads 1 as soon as the generator feature is enabled,
with nothing wired. Until the FranklinWH app shows what that means, genStat 1 with no model
or rated power is shown raw and unconfirmed, never "Running", and is not hardware evidence."""
from franklinwh_direct_connect_bridge import generator
from test_generator import NO_GEN, RUNNING

ENABLED_ONLY = {**NO_GEN, "genEn": 1, "genStat": 1}


def test_enabled_with_no_hardware_is_not_running():
    g = generator.build(ENABLED_ONLY)
    assert g["running"] is False
    assert "Running" not in g["state_name"]
    assert g["state_name"] == "genStat 1 (unconfirmed)"
    assert g["state_unconfirmed"] is True


def test_genstat_is_not_hardware_evidence():
    assert generator.configured(ENABLED_ONLY) is False
    assert generator.build(ENABLED_ONLY)["evidence"]["run_state"] is None


def test_with_a_model_and_rating_the_state_is_shown():
    g = generator.build(RUNNING)
    assert g["running"] is True and g["state_name"] == "Running / ON"
    assert g["state_unconfirmed"] is False and generator.configured(RUNNING) is True


def test_standby_is_unchanged():
    g = generator.build(NO_GEN)
    assert g["state_name"] == "Standby / OFF" and g["state_unconfirmed"] is False
