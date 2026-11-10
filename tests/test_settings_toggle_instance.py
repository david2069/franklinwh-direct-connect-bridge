"""#170: Disable/Enable on an HA instance called this.loadNotif(), which does not exist, so
the change applied and then reported an error. The method is loadNotify()."""
import pathlib
import re

JS = (pathlib.Path(__file__).resolve().parents[1]
      / "src/franklinwh_direct_connect_bridge/static/js/settings_tab.js").read_text()


def test_every_load_call_names_a_defined_method():
    called = set(re.findall(r"this\.(load\w+)\(", JS))
    defined = set(re.findall(r"^\s+(?:async\s+)?(load\w+)\(", JS, re.M))
    assert called <= defined, called - defined
