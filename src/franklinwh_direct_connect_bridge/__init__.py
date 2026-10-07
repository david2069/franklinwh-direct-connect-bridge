"""franklinwh-direct-connect-bridge — REST + MQTT bridge for the FranklinWH aGate local API."""

from importlib.metadata import PackageNotFoundError, version as _dist_version

try:
    # Single source of truth: the installed distribution's metadata, which comes
    # from pyproject.toml. A hardcoded literal here drifted to 0.1.0 while the
    # project was at 0.2.0, and because this value is published as the MQTT
    # device's `sw_version`, every Home Assistant device reported the wrong
    # version. Derive it instead so it cannot drift again.
    __version__ = _dist_version("franklinwh-direct-connect-bridge")
except PackageNotFoundError:          # running from a source tree, not installed
    __version__ = "0.0.0+unknown"
