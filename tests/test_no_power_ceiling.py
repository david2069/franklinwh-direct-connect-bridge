"""No fixed ceiling on a power reading, anywhere in the data path.

Cross-bridge audit, 2026-10-16. The Modbus Bridge carried a hard-coded 15 kW "sanity" cap
in two places — the poller and the history recorder — added to filter 0xFFFF corruption on
the assumption that nothing residential exceeds 15 kW. A real user with 33 kW DC (76×
Enphase IQ8Plus) had midday solar replaced by stale values and every history row above
15 kW dropped.

This bridge has no such cap, and these tests exist to keep it that way: a reading the
hardware reports is data, and a constant chosen from what seemed reasonable in one house
is not a measurement. If corruption ever needs filtering, the backstop belongs at an
ABSURD value (hundreds of kW), not at a plausible one.
"""
import pytest

from franklinwh_direct_connect_bridge import energy_flow
from franklinwh_direct_connect_bridge.db import MetricsStore

BIG = 33_000.0          # 33 kW DC — the user whose readings were being thrown away
HUGE = 120_000.0        # a commercial array; still a reading, not a glitch


@pytest.fixture
def store(tmp_path):
    return MetricsStore(str(tmp_path / "m.db"))


def test_a_33kw_sample_is_stored_unchanged(store):
    store.insert({"soc": 50.0, "solar_w": BIG, "grid_w": -BIG, "load_w": 1200.0,
                  "battery_w": 0.0}, ts=1_700_000_000)
    rows = store.query(1_699_999_000, 1_700_001_000, None)
    assert len(rows) == 1
    assert rows[0]["solar_w"] == BIG            # not clipped
    assert rows[0]["grid_w"] == -BIG            # export is negative and just as large


def test_even_an_implausibly_large_reading_is_kept(store):
    """Keeping it is the honest choice: the alternative silently rewrites history."""
    store.insert({"solar_w": HUGE}, ts=1_700_000_100)
    assert store.query(1_700_000_000, 1_700_000_200, None)[0]["solar_w"] == HUGE


def test_the_energy_integration_does_not_cap_power(store):
    """kWh comes from integrating W over time; a cap there understates the day."""
    # Solar all going to the home, so the arc split is unambiguous.
    # Solar all going to the home, so the arc split is unambiguous (``home_w`` is the
    # key the splitter reads).
    samples = [{"ts": 0, "solar_w": BIG, "home_w": BIG},
               {"ts": 3600, "solar_w": BIG, "home_w": BIG}]
    out = energy_flow.integrate(samples, max_gap_s=7200)
    # 33 kW for an hour is 33 kWh, whatever anyone thinks is reasonable for a house.
    assert out["solar_to_home"] == pytest.approx(33.0, abs=0.2)


def test_the_only_gap_guard_is_relative_not_a_constant():
    """The one bound in this path is a TIME gap, and it is derived from the series' own
    median step — the same lesson, already applied on a different axis."""
    assert energy_flow._gap_cap([10.0, 10.0, 10.0]) == 60.0      # floor, not a ceiling
    assert energy_flow._gap_cap([300.0, 300.0, 300.0]) == 900.0  # scales with the data


def test_no_power_ceiling_constant_exists_in_the_data_path():
    """A grep-style guard: the defect was a literal sitting in two files."""
    import pathlib
    import re
    root = pathlib.Path(__file__).resolve().parents[1] / "src/franklinwh_direct_connect_bridge"
    suspicious = re.compile(r"\b1[05]_?000\b")
    for f in (root / "poller.py", root / "db.py", root / "energy_flow.py",
              root / "publish" / "entities.py"):
        text = f.read_text()
        for i, line in enumerate(text.splitlines(), start=1):
            if suspicious.search(line) and any(
                    w in line.lower() for w in ("_w", "watt", "power", "solar", "grid")):
                raise AssertionError(f"possible power ceiling at {f.name}:{i}: {line.strip()}")
