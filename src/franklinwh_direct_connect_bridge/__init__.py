"""franklinwh-direct-connect-bridge — REST + MQTT bridge for the FranklinWH aGate local API."""

from importlib.metadata import PackageNotFoundError, version as _dist_version
from pathlib import Path as _Path

_DIST = "franklinwh-direct-connect-bridge"


def _source_tree_version() -> str | None:
    """The version in the pyproject.toml of the source tree this code runs from, if any.

    An editable install's metadata is frozen at install time: after a version bump (or
    when another checkout's code is put first on the path) it reports an old version for
    new code. When the code runs from a source tree, that tree's pyproject.toml is the
    truth for it."""
    pyproject = _Path(__file__).resolve().parents[2] / "pyproject.toml"
    try:
        import tomllib
        project = tomllib.loads(pyproject.read_text(encoding="utf-8")).get("project", {})
    except (OSError, ValueError, ImportError):
        return None
    return project.get("version") if project.get("name") == _DIST else None


# Single source of truth: pyproject.toml — read directly from a source tree, or through
# the installed distribution's metadata. A hardcoded literal here drifted to 0.1.0 while
# the project was at 0.2.0, and because this value is published as the MQTT device's
# `sw_version`, every Home Assistant device reported the wrong version. Derive it instead
# so it cannot drift again.
__version__ = _source_tree_version()
if __version__ is None:
    try:
        __version__ = _dist_version(_DIST)
    except PackageNotFoundError:      # neither a source tree nor installed
        __version__ = "0.0.0+unknown"
