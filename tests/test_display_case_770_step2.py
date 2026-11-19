"""#770 step 2: the remaining UI-only wording reads in Sentence case — the health pattern
level (it was lower case in one place and UPPER in the report picker) and the TOU card's
"unknown" mode."""
import pathlib

T = pathlib.Path(__file__).resolve().parents[1] / "src" / "franklinwh_direct_connect_bridge" / "templates"
HEALTH = (T / "tabs" / "health.html").read_text()
SCHED = (T / "tabs" / "scheduler.html").read_text()


def test_health_levels_read_the_same_way():
    assert 'x-text="$store.app.sentence(p.level.toLowerCase())"' in HEALTH
    assert "${$store.app.sentence(p.level)}" in HEALTH
    assert 'x-text="p.level.toLowerCase()"' not in HEALTH


def test_tou_mode_unknown_is_sentence_case():
    assert "tou.mode || 'Unknown'" in SCHED and "tou.mode || 'unknown'" not in SCHED
