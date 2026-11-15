"""Owner 2026-11-13: Import tariff takes pasted JSON as well as a file (on a phone there
was no way to get a tariff in without a file). One dialog: paste or choose a file, Check
(the dry-run preview), Import. Results stay in the dialog, no toasts."""
import pathlib

PKG = pathlib.Path(__file__).resolve().parents[1] / "src" / "franklinwh_direct_connect_bridge"
HTML = ((PKG / "templates" / "tabs" / "settings.html").read_text()   # + Plans & meters (#613)
        + (PKG / "templates" / "partials" / "plans_meters.html").read_text())
JS = (PKG / "static" / "js" / "settings_tab.js").read_text()


def test_dialog_has_paste_file_check_import_and_result():
    for tid in ("tariff-import-dialog", "tariff-import-paste", "tariff-import-file",
                "tariff-import-check", "tariff-import-apply", "tariff-import-result"):
        assert f'data-testid="{tid}"' in HTML
    assert "openTariffImport(" in HTML


def test_import_runs_from_the_text_and_never_toasts():
    a = JS.index("openTariffImport(meterId)")
    b = JS.index("editUtility(u)")
    code = JS[a:b]
    assert "dry_run=true" in code and "api/tariffs/import" in code
    assert "JSON.parse(" in code and ".text" in code
    assert "toast(" not in code


def test_after_import_the_dialog_says_what_was_added_and_offers_done():
    """#654 (owner 2026-11-16): after Import there was one small green line under the
    preview and only the corner × to leave; Check again offered a second Import that would
    end the plan just added. Now the form makes way for the result and a Done button."""
    assert 'data-testid="tariff-import-done"' in HTML
    assert 'data-testid="tariff-import-done-close"' in HTML
    form = HTML.index('data-testid="tariff-import-form"')
    assert 'x-show="!tariffImp.done"' in HTML[form - 200:form + 200]
    a = JS.index("async tariffImportApply()")
    code = JS[a:JS.index("editUtility(u)")]
    assert "t.result = {" in code and "t.preview = null" in code
    a = JS.index("async tariffImportCheck()")
    assert "if (t.done) return;" in JS[a:a + 200]
