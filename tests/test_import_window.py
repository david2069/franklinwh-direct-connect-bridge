"""Import opens the bridge's own window first (owner 2026-11-18): on Android the file
picker is the system's full-screen file browser with no Cancel. The window offers Choose
file…, Paste JSON and Cancel; paste goes through the same import as a file, and errors show
in the window, not as toasts."""
import pathlib
import re

PKG = pathlib.Path(__file__).resolve().parents[1] / "src" / "franklinwh_direct_connect_bridge"
TPL = PKG / "templates"
PART = (TPL / "partials" / "import_window.html").read_text() if (TPL / "partials" / "import_window.html").exists() else ""
SCHED = (TPL / "tabs" / "scheduler.html").read_text()
SJS = (PKG / "static" / "js" / "scheduler_tab.js").read_text()


def test_the_shared_window_has_choose_paste_and_cancel():
    for tid in ("import-window", "import-choose-file", "import-paste", "import-paste-submit",
                "import-cancel", "import-msg"):
        assert f'data-testid="{tid}"' in PART, tid
    assert 'type="file"' in PART
    # above the bottom nav like every dialog (#734)
    assert re.search(r'class="fixed inset-0 z-\[1\d\d\]', PART)


def test_scheduler_import_opens_the_window_not_the_picker():
    btn = SCHED[:SCHED.index(">Import</button>")]
    btn = btn[btn.rindex("<button"):]
    assert "openImportWindow()" in btn and "triggerImport()" not in btn
    assert '{% include "partials/import_window.html" %}' in SCHED


def test_paste_and_file_share_one_import_path_and_report_in_the_window():
    body = SJS[SJS.index("async importText("):]
    body = body[:body.index("\n    },")]
    assert "api/schedules/import?dry_run=true" in body
    assert "toast(" not in body                           # results stay in the window
    file_fn = SJS[SJS.index("async onImportFile("):]
    file_fn = file_fn[:file_fn.index("\n    },")]
    assert "importText(" in file_fn                      # the file goes the same way


def test_every_file_input_is_inside_a_window():
    """No import button opens the system picker directly any more."""
    for f in TPL.rglob("*.html"):
        for m in re.finditer(r'\$refs\.(\w+)\.click\(\)', f.read_text()):
            ref = m.group(1)
            assert f.name in ("import_window.html", "plans_meters.html"), (f.name, ref)


def test_tariff_import_window_has_a_cancel_button():
    pm = (TPL / "partials" / "plans_meters.html").read_text()
    form = pm[pm.index('data-testid="tariff-import-form"'):]
    assert 'data-testid="tariff-import-cancel"' in form[:form.index("tariff-import-result")]
