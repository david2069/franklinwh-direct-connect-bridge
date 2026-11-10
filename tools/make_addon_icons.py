#!/usr/bin/env python3
"""Generate the Home Assistant add-on icon.png and logo.png — stdlib only.

The Supervisor shows these in the add-on store and the add-on page; without them the
add-on renders with the generic puzzle piece. They are generated rather than committed as
opaque binaries so the shape can be re-derived: it is the same mark as the web UI's
favicon (a green rounded square with a white bolt), defined once below.

Sizes follow the Home Assistant add-on convention: icon 128x128, logo 250x150.

Usage: python3 tools/make_addon_icons.py [outdir]
"""
from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path

GREEN = (16, 185, 129)          # #10b981 — the UI's accent, and the favicon's
WHITE = (255, 255, 255)
SS = 3                          # supersampling factor per axis (anti-aliasing)

#: The favicon's bolt path, in its own 24x24 coordinate space:
#: M13 3 L6 13 h4 l-1 8 l7 -10 h-4 z
BOLT = [(13, 3), (6, 13), (10, 13), (9, 21), (16, 11), (12, 11)]
RADIUS_24 = 5.0                 # the favicon's rect corner radius, same space


def _inside_polygon(x: float, y: float, poly) -> bool:
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            xi = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < xi:
                inside = not inside
    return inside


def _inside_rounded_rect(x: float, y: float, w: float, h: float, r: float) -> bool:
    if x < 0 or y < 0 or x > w or y > h:
        return False
    cx = min(max(x, r), w - r)
    cy = min(max(y, r), h - r)
    return (x - cx) ** 2 + (y - cy) ** 2 <= r * r


def _badge_rgba(size: int) -> bytearray:
    """A size x size RGBA badge: green rounded square, white bolt, transparent outside."""
    scale = size / 24.0
    r = RADIUS_24 * scale
    bolt = [(bx * scale, by * scale) for bx, by in BOLT]
    rows = bytearray()
    for py in range(size):
        row = bytearray()
        for px in range(size):
            hits_bg = hits_fg = 0
            for sy in range(SS):
                for sx in range(SS):
                    x = px + (sx + 0.5) / SS
                    y = py + (sy + 0.5) / SS
                    if _inside_rounded_rect(x, y, size, size, r):
                        hits_bg += 1
                        if _inside_polygon(x, y, bolt):
                            hits_fg += 1
            total = SS * SS
            if not hits_bg:
                row += bytes((0, 0, 0, 0))
                continue
            alpha = round(255 * hits_bg / total)
            mix = hits_fg / hits_bg                      # bolt coverage within the badge
            colour = tuple(round(GREEN[i] * (1 - mix) + WHITE[i] * mix) for i in range(3))
            row += bytes((*colour, alpha))
        rows += row
    return rows


def _png(width: int, height: int, rgba_rows: bytes) -> bytes:
    raw = bytearray()
    stride = width * 4
    for y in range(height):
        raw.append(0)                                    # filter type 0 (None)
        raw += rgba_rows[y * stride:(y + 1) * stride]

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + chunk(b"IEND", b""))


def _centre(badge: bytes, badge_size: int, width: int, height: int) -> bytes:
    """Place the square badge on a transparent canvas of width x height."""
    out = bytearray(width * height * 4)
    ox = (width - badge_size) // 2
    oy = (height - badge_size) // 2
    for y in range(badge_size):
        src = y * badge_size * 4
        dst = ((y + oy) * width + ox) * 4
        out[dst:dst + badge_size * 4] = badge[src:src + badge_size * 4]
    return bytes(out)


def main(argv: list[str]) -> int:
    out = Path(argv[0]) if argv else Path(__file__).resolve().parents[1]
    icon = _badge_rgba(128)
    (out / "icon.png").write_bytes(_png(128, 128, bytes(icon)))
    badge = _badge_rgba(120)
    (out / "logo.png").write_bytes(_png(250, 150, _centre(bytes(badge), 120, 250, 150)))
    print(f"wrote {out / 'icon.png'} (128x128) and {out / 'logo.png'} (250x150)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
