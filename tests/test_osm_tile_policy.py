"""OpenStreetMap's tile servers block requests without a Referer ("Access blocked", owner
2026-11-25). Home Assistant serves its pages with ``Referrer-Policy: no-referrer``, so in the
HA panel the CloudFront PoPs map sent none. The tile layer now sends the page's origin, and
uses tile.openstreetmap.org without the old a/b/c subdomains, as the tile usage policy asks."""
import pathlib

JS = (pathlib.Path(__file__).resolve().parents[1]
      / "src/franklinwh_direct_connect_bridge/static/js/network_tab.js").read_text()


def test_tiles_send_the_origin_as_referer():
    assert "referrerPolicy: 'strict-origin-when-cross-origin'" in JS


def test_tiles_use_the_policy_url_and_keep_the_attribution():
    assert "'https://tile.openstreetmap.org/{z}/{x}/{y}.png'" in JS
    assert "{s}.tile.openstreetmap.org" not in JS
    assert "openstreetmap.org/copyright" in JS
