"""#169: `%ha:<instance>:<entity>%` in a schedule's message is replaced like any other id."""
from franklinwh_direct_connect_bridge.scheduler import substitute


def test_an_ha_placeholder_is_replaced():
    snap = {"ha:i1:sensor.amber_general_price": 31.5, "battery.soc_pct": 80}
    assert substitute("Price %ha:i1:sensor.amber_general_price%c, SoC %battery.soc_pct%%",
                      snap) == "Price 31.5c, SoC 80%"


def test_an_unread_ha_placeholder_prints_a_question_mark():
    assert substitute("x %ha:i1:sensor.gone%", {}) == "x ?"


def test_text_that_only_looks_like_one_is_left_alone():
    assert substitute("at 10:30% of 5%", {}) == "at 10:30% of 5%"
