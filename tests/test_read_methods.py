"""READ_METHODS must stay in step with the library catalog.

Regression guard: the set was hand-maintained and had fallen 7 methods behind
(battery_cells, power_electronics, device_firmware, device_states, device_check,
agate_serial, energy_history) — the same drift the library itself hit.
"""

from franklinwh_local import catalog
from franklinwh_local.client import LocalClient

from franklinwh_direct_connect_bridge.client import READ_METHODS


def test_every_catalog_read_with_a_client_method_is_exposed():
    missing = {
        info.name for info in catalog.CATALOG.values()
        if callable(getattr(LocalClient, info.name, None))
        and info.name != "login"
    } - READ_METHODS
    assert not missing, f"catalog reads not exposed as endpoints: {sorted(missing)}"


def test_new_per_device_reads_are_present():
    for name in ("battery_cells", "power_electronics", "device_firmware",
                 "device_states", "device_check"):
        assert name in READ_METHODS


def test_extras_not_backed_by_a_catalog_entry_are_kept():
    """firmware comes from the login manifest; grid_profile is a fan-out."""
    assert "firmware" in READ_METHODS
    assert "grid_profile" in READ_METHODS


def test_login_is_not_exposed_as_a_read():
    assert "login" not in READ_METHODS


def test_every_exposed_name_is_actually_callable():
    """An endpoint that cannot be invoked is worse than a missing one."""
    for name in READ_METHODS:
        if name == "grid_profile":
            continue  # convenience wrapper, verified by its own tests
        assert callable(getattr(LocalClient, name, None)), name
