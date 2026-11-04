"""#487: a non-editable pip install must carry the whole web UI, every file under static/
and templates/ (subfolders included), not only the top-level ones."""
import pathlib
import subprocess
import sys
import zipfile

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PKG = ROOT / "src/franklinwh_direct_connect_bridge"


@pytest.fixture(scope="module")
def wheel_files(tmp_path_factory):
    out = tmp_path_factory.mktemp("wheel")
    subprocess.run([sys.executable, "-m", "pip", "wheel", "--no-deps",
                    "--quiet", "-w", str(out), str(ROOT)], check=True)
    whl = next(out.glob("franklinwh_direct_connect_bridge-*.whl"))
    return set(zipfile.ZipFile(whl).namelist())


@pytest.mark.parametrize("folder", ["static", "templates"])
def test_every_ui_file_is_in_the_wheel(wheel_files, folder):
    want = {f"franklinwh_direct_connect_bridge/{p.relative_to(PKG).as_posix()}"
            for p in (PKG / folder).rglob("*") if p.is_file() and "__pycache__" not in p.parts}
    missing = sorted(want - wheel_files)
    assert not missing, f"{len(missing)} not packaged, e.g. {missing[:5]}"


def test_the_pages_the_main_page_needs_are_there(wheel_files):
    for f in ("static/css/design-system.css", "static/js/alpinejs-3.14.1.min.js",
              "templates/tabs/settings.html", "templates/partials/dialog_msg.html"):
        assert f"franklinwh_direct_connect_bridge/{f}" in wheel_files, f
