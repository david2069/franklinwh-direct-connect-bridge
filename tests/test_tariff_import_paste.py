"""Owner 2026-11-13: Import tariff takes pasted JSON as well as a file (on a phone there
was no way to get a tariff in without a file). One dialog: paste or choose a file, Check
(the dry-run preview), Import. Results stay in the dialog, no toasts."""
import pathlib

PKG = pathlib.Path(__file__).resolve().parents[1] / "src" / "franklinwh_direct_connect_bridge"
HTML = (PKG / "templates" / "tabs" / "settings.html").read_text()
JS = (PKG / "static" / "js" / "settings_tab.js").read_text()


def test_dialog_has_paste_file_check_import_and_result():
    for tid in ("tariff-import-dialog", "tariff-import-paste", "tariff-import-file",
                "tariff-import-check", "tariff-import-apply", "tariff-import-result"):
        assert f'data-testid="{tid}"' in HTML
    assert "openTariffImport()" in HTML


def test_import_runs_from_the_text_and_never_toasts():
    a = JS.index("openTariffImport()")
    b = JS.index("editUtility(u)")
    code = JS[a:b]
    assert "dry_run=true" in code and "api/tariffs/import" in code
    assert "JSON.parse(" in code and ".text" in code
    assert "toast(" not in code
