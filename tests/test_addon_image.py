"""#243: the add-on ships as a prebuilt GHCR image, so config.yaml, build.yaml and the
publish workflow must agree. A mismatch is an update that fails for every user: the
Supervisor pulls {image}:{version}, and nothing else exists to fall back on."""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
CONFIG = (ROOT / "config.yaml").read_text()
BUILD = (ROOT / "build.yaml").read_text()
WF = (ROOT / ".github/workflows/publish-image.yml").read_text()


def _arches(text, indent):
    return re.findall(rf"^{indent}([a-z0-9]+)", text, re.M)


def test_config_names_the_published_image():
    m = re.search(r'^image: "([^"]+)"', CONFIG, re.M)
    assert m, "config.yaml has no image:"
    assert m.group(1) == "ghcr.io/david2069/{arch}-franklinwh-direct-connect-bridge"
    assert 'image="ghcr.io/david2069/${{ matrix.arch }}-franklinwh-direct-connect-bridge"' in WF


def test_every_arch_is_built_and_has_a_base():
    block = CONFIG.split("\narch:\n", 1)[1].split("\n\n", 1)[0]
    cfg = re.findall(r"^  - ([a-z0-9]+)$", block, re.M)
    wf = re.findall(r"- arch: ([a-z0-9]+)", WF)
    base = re.findall(r'^  ([a-z0-9]+): +"', BUILD.split("build_from:", 1)[1], re.M)
    assert cfg and sorted(cfg) == sorted(wf), (cfg, wf)
    assert set(cfg) <= set(base), (cfg, base)


def test_a_published_tag_is_never_overwritten():
    assert "already exists" in WF and "docker manifest inspect" in WF


def test_publishing_is_manual_only():
    """The image must exist before the release merges; no automatic push on main."""
    on = WF.split("\non:", 1)[1].split("\npermissions:", 1)[0]
    assert "workflow_dispatch" in on and "push:" not in on.split("inputs:")[0]
