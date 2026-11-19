"""#782: publishing the Bridge on PyPI. Pins the package metadata PyPI shows, the README links
that must work off GitHub, the release workflow's gating, and the G1s pip leg's PyPI route."""
import importlib.util
import pathlib
import re
import tomllib

ROOT = pathlib.Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("standalone_acceptance", ROOT / "tools/standalone_acceptance.py")
acc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(acc)

PROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]


def test_author_email_is_the_github_noreply_address():
    # PyPI displays it publicly; the owner chose the noreply address (2026-11-20).
    emails = [a.get("email", "") for a in PROJECT["authors"]]
    assert emails == ["david2069@users.noreply.github.com"]


def test_project_urls_point_at_this_repository_and_docs_site():
    urls = PROJECT["urls"]
    assert set(urls) >= {"Homepage", "Documentation", "Issues", "Changelog"}
    assert urls["Documentation"] == "https://david2069.github.io/franklinwh-direct-connect-bridge/"
    for key in ("Homepage", "Issues", "Changelog"):
        assert urls[key].startswith("https://github.com/david2069/franklinwh-direct-connect-bridge")


def test_classifiers_match_the_declared_python_floor():
    cls = PROJECT["classifiers"]
    assert "License :: OSI Approved :: MIT License" in cls
    floor = PROJECT["requires-python"].removeprefix(">=")
    versions = [c.rsplit(":: ", 1)[1] for c in cls if re.fullmatch(r"Programming Language :: Python :: 3\.\d+", c)]
    assert versions and min(versions, key=lambda v: tuple(map(int, v.split(".")))) == floor


def test_no_direct_url_dependencies():
    # PyPI rejects an upload whose metadata has a direct (URL) reference.
    deps = PROJECT["dependencies"] + [d for ds in PROJECT["optional-dependencies"].values() for d in ds]
    assert not [d for d in deps if " @ " in d or "://" in d]


def test_readme_has_no_relative_links():
    # The README is the PyPI project page, where a relative link resolves to nothing.
    text = (ROOT / "README.md").read_text()
    targets = re.findall(r"\]\(([^)]+)\)", text) + re.findall(r'src="([^"]+)"', text)
    relative = [t for t in targets if not re.match(r"(https?:|#|mailto:)", t)]
    assert relative == []


def test_readme_github_links_resolve_to_files_in_this_checkout():
    prefix = "https://github.com/david2069/franklinwh-direct-connect-bridge/blob/main/"
    text = (ROOT / "README.md").read_text()
    paths = {m.split("#")[0] for m in re.findall(re.escape(prefix) + r"([^)\s]+)", text)}
    assert paths
    assert [p for p in paths if not (ROOT / p).exists()] == []


def test_release_workflow_publishes_only_on_a_version_tag_by_trusted_publishing():
    wf = (ROOT / ".github/workflows/release.yml").read_text()
    assert re.search(r"tags:\s*\[\"v\*\"\]", wf)
    assert "pull_request:" in wf
    publish = wf.split("\n  publish:", 1)[1]
    assert "if: startsWith(github.ref, 'refs/tags/v')" in publish
    assert "environment: pypi" in publish
    assert "id-token: write" in publish
    assert "pypa/gh-action-pypi-publish@release/v1" in publish
    # No stored token: trusted publishing only.
    assert "password:" not in wf and "PYPI_API_TOKEN" not in wf


def test_release_workflow_checks_the_tag_matches_the_built_version():
    wf = (ROOT / ".github/workflows/release.yml").read_text()
    assert "twine check" in wf
    assert 'want="${GITHUB_REF_NAME#v}"' in wf


def test_pip_leg_installs_the_git_ref_by_default():
    assert acc.pip_requirement("main", "0.5.54", False) == (
        "franklinwh-direct-connect-bridge[cloud] @ git+https://github.com/david2069/franklinwh-direct-connect-bridge@main")


def test_pip_leg_from_pypi_pins_the_release_under_test():
    assert acc.pip_requirement("main", "0.5.54", True) == "franklinwh-direct-connect-bridge[cloud]==0.5.54"


def test_from_pypi_flag_is_accepted(monkeypatch, tmp_path):
    seen = {}

    def fake_start_pip(requirement, *a, **k):
        seen["req"] = requirement
        raise SystemExit(0)  # stop before anything is installed or run

    monkeypatch.setattr(acc, "start_pip", fake_start_pip)
    try:
        acc.main(["pip", "--from-pypi", "--version", "0.5.54", "--out", str(tmp_path)])
    except SystemExit:
        pass
    assert seen["req"] == "franklinwh-direct-connect-bridge[cloud]==0.5.54"
