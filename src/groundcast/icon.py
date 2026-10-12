"""The Groundcast icon: one drawing, written out as SVG (web) and as PNG, ICO, and ICNS (shortcuts).

The mark is a G drawn as sound waves: two open rings spread from a glowing
source at the centre, and the G's crossbar is a warm ground line the source
stands on, as every sentence of a session stands on its sources. All shapes
are defined once below, in a unit box (0 to 1, y down); `svg()` writes them
as vector shapes and `render()` samples them several times per pixel, so
the two outputs match without any binary image in the repository.
web/static/favicon.svg is `svg()`'s output (a test keeps them the same).
"""

from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path

import numpy as np

CORNER = 0.225  # corner radius of the rounded square
BACKGROUND = ("#0a2226", "#145650")  # top, bottom
HIGHLIGHT = ("#ffffff", 0.16, (0.28, 0.18), 0.7)  # soft light: colour, opacity, centre, radius
CENTRE = (0.5, 0.5)
GAP = 38.0  # degrees: the G's opening, from straight right towards the top
RINGS = ((0.31, 0.09, 1.0), (0.19, 0.046, 0.55))  # radius, stroke width, opacity
RING_COLOURS = ("#fff3dc", "#f4a640", 0.19, 0.81)  # top colour, bottom colour, from y, to y
BAR = (0.31, 0.09)  # from the centre to this distance right, stroke width
BAR_COLOURS = ("#f7b84e", "#ec8f2e")  # at the centre, at the end
GLOW = ("#ffc46b", 0.7, 0.22)  # around the source: colour, opacity at the centre, radius
SOURCE = ("#fff7e8", 0.066)  # colour, radius

SAMPLES = 4  # per pixel side
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)
ICNS_TYPES = {128: b"ic07", 256: b"ic08", 512: b"ic09"}
SVG_BOX = 100.0


def _rgb(hex_colour: str) -> np.ndarray:
    return np.array([int(hex_colour[i : i + 2], 16) for i in (1, 3, 5)], dtype=np.float32)


def ring_ends(radius: float) -> tuple[tuple[float, float], tuple[float, float]]:
    """Where a ring starts (at the top of the opening) and ends (straight right, on the crossbar)."""
    cx, cy = CENTRE
    a = math.radians(GAP)
    return (cx + radius * math.cos(a), cy - radius * math.sin(a)), (cx + radius, cy)


# Raster


def _mix(a: np.ndarray, b: np.ndarray, t: np.ndarray) -> np.ndarray:
    t = np.clip(t, 0.0, 1.0)[..., None]
    return a + (b - a) * t


def _paint(rgb: np.ndarray, colour: np.ndarray, cover: np.ndarray) -> np.ndarray:
    """Paint colour (one colour, or one per sample) with coverage 0 to 1 over an opaque picture."""
    c = cover[..., None]
    return rgb * (1 - c) + colour * c


def render(size: int) -> np.ndarray:
    """RGBA pixels, shape (size, size, 4), uint8."""
    n = size * SAMPLES
    coords = (np.arange(n, dtype=np.float32) + 0.5) / n
    x, y = np.meshgrid(coords, coords)
    cx, cy = CENTRE

    rgb = _mix(_rgb(BACKGROUND[0]), _rgb(BACKGROUND[1]), y)
    colour, opacity, (hx, hy), radius = HIGHLIGHT
    rgb = _paint(rgb, _rgb(colour), opacity * np.clip(1 - np.hypot(x - hx, y - hy) / radius, 0, 1))
    colour, opacity, radius = GLOW
    rgb = _paint(rgb, _rgb(colour), opacity * np.clip(1 - np.hypot(x - cx, y - cy) / radius, 0, 1) ** 2)

    top, bottom, y0, y1 = RING_COLOURS
    ring_rgb = _mix(_rgb(top), _rgb(bottom), (y - y0) / (y1 - y0))
    dx, dy = x - cx, y - cy
    angle = np.degrees(np.arctan2(dy, dx)) % 360.0  # 0 straight right, growing clockwise on screen
    for radius, width, opacity in RINGS:
        (sx, sy), (ex, ey) = ring_ends(radius)
        to_ends = np.minimum(np.hypot(x - sx, y - sy), np.hypot(x - ex, y - ey))
        d = np.where(angle <= 360.0 - GAP, np.abs(np.hypot(dx, dy) - radius), to_ends)
        rgb = _paint(rgb, ring_rgb, opacity * (d <= width / 2))

    length, width = BAR
    t = np.clip((x - cx) / length, 0.0, 1.0)
    bar = np.hypot(x - (cx + t * length), y - cy) <= width / 2
    rgb = _paint(rgb, _mix(_rgb(BAR_COLOURS[0]), _rgb(BAR_COLOURS[1]), t), bar.astype(np.float32))
    colour, radius = SOURCE
    rgb = _paint(rgb, _rgb(colour), (np.hypot(x - cx, y - cy) <= radius).astype(np.float32))

    # The rounded square cuts it out.
    qx = np.maximum(np.abs(x - 0.5) - (0.5 - CORNER), 0.0)
    qy = np.maximum(np.abs(y - 0.5) - (0.5 - CORNER), 0.0)
    shape = (qx * qx + qy * qy <= CORNER * CORNER).astype(np.float32)
    rgba = np.concatenate([rgb * shape[..., None], (shape * 255.0)[..., None]], axis=-1)
    # Average each block of samples into one pixel, colours weighted by coverage.
    blocks = rgba.reshape(size, SAMPLES, size, SAMPLES, 4).mean(axis=(1, 3))
    alpha = blocks[..., 3:4]
    colour_out = np.where(alpha > 0, blocks[..., :3] * 255.0 / np.maximum(alpha, 1e-6), 0.0)
    return np.clip(np.concatenate([colour_out, alpha], axis=-1) + 0.5, 0, 255).astype(np.uint8)


# Vector


def _n(value: float) -> str:
    return f"{value * SVG_BOX:.2f}".rstrip("0").rstrip(".")


def svg(prefix: str = "gc") -> str:
    """The icon as an SVG document; prefix keeps its IDs unique when several copies share a page."""
    box = _n(1)
    cx, cy = CENTRE
    hi_colour, hi_opacity, (hx, hy), hi_radius = HIGHLIGHT
    glow_colour, glow_opacity, glow_radius = GLOW
    top, bottom, y0, y1 = RING_COLOURS
    length, bar_width = BAR
    source_colour, source_radius = SOURCE
    rings = ""
    for radius, width, opacity in RINGS:
        (sx, sy), (ex, ey) = ring_ends(radius)
        rings += (f'<path d="M{_n(sx)} {_n(sy)}A{_n(radius)} {_n(radius)} 0 1 0 {_n(ex)} {_n(ey)}" '
                  f'stroke-width="{_n(width)}" stroke-opacity="{opacity:g}"/>')  # fmt: skip
    return "".join([
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {box} {box}" role="img" aria-label="Groundcast">',
        "<defs>",
        f'<clipPath id="{prefix}-shape"><rect width="{box}" height="{box}" rx="{_n(CORNER)}"/></clipPath>',
        f'<linearGradient id="{prefix}-bg" x1="0" y1="0" x2="0" y2="{box}" gradientUnits="userSpaceOnUse">'
        f'<stop offset="0" stop-color="{BACKGROUND[0]}"/><stop offset="1" stop-color="{BACKGROUND[1]}"/>'
        "</linearGradient>",
        f'<radialGradient id="{prefix}-hi" cx="{_n(hx)}" cy="{_n(hy)}" r="{_n(hi_radius)}" '
        f'gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="{hi_colour}" stop-opacity="{hi_opacity:g}"/>'
        f'<stop offset="1" stop-color="{hi_colour}" stop-opacity="0"/></radialGradient>',
        f'<radialGradient id="{prefix}-glow" cx="{_n(cx)}" cy="{_n(cy)}" r="{_n(glow_radius)}" '
        f'gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="{glow_colour}" '
        f'stop-opacity="{glow_opacity:g}"/><stop offset=".5" stop-color="{glow_colour}" '
        f'stop-opacity="{glow_opacity / 4:g}"/><stop offset="1" stop-color="{glow_colour}" stop-opacity="0"/>'
        "</radialGradient>",
        f'<linearGradient id="{prefix}-ring" x1="0" y1="{_n(y0)}" x2="0" y2="{_n(y1)}" '
        f'gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="{top}"/>'
        f'<stop offset="1" stop-color="{bottom}"/></linearGradient>',
        f'<linearGradient id="{prefix}-bar" x1="{_n(cx)}" y1="0" x2="{_n(cx + length)}" y2="0" '
        f'gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="{BAR_COLOURS[0]}"/>'
        f'<stop offset="1" stop-color="{BAR_COLOURS[1]}"/></linearGradient>',
        "</defs>",
        f'<g clip-path="url(#{prefix}-shape)">',
        f'<rect width="{box}" height="{box}" fill="url(#{prefix}-bg)"/>',
        f'<rect width="{box}" height="{box}" fill="url(#{prefix}-hi)"/>',
        f'<circle cx="{_n(cx)}" cy="{_n(cy)}" r="{_n(glow_radius)}" fill="url(#{prefix}-glow)"/>',
        f'<g fill="none" stroke="url(#{prefix}-ring)" stroke-linecap="round">{rings}</g>',
        f'<path d="M{_n(cx)} {_n(cy)}H{_n(cx + length)}" stroke="url(#{prefix}-bar)" '
        f'stroke-width="{_n(bar_width)}" stroke-linecap="round"/>',
        f'<circle cx="{_n(cx)}" cy="{_n(cy)}" r="{_n(source_radius)}" fill="{source_colour}"/>',
        "</g></svg>\n",
    ])  # fmt: skip


# Files


def png(size: int) -> bytes:
    pixels = render(size)
    raw = b"".join(b"\x00" + pixels[row].tobytes() for row in range(size))  # filter type 0 per row

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)  # 8-bit RGBA
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


def ico(sizes: tuple[int, ...] = ICO_SIZES) -> bytes:
    """A Windows icon holding one PNG image per size (supported since Windows Vista)."""
    images = [png(s) for s in sizes]
    offset = 6 + 16 * len(sizes)
    entries = b""
    for size, data in zip(sizes, images):
        side = 0 if size >= 256 else size  # 0 means 256
        entries += struct.pack("<BBBBHHII", side, side, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    return struct.pack("<HHH", 0, 1, len(sizes)) + entries + b"".join(images)


def icns(types: dict[int, bytes] = ICNS_TYPES) -> bytes:
    """A macOS icon holding PNG images."""
    body = b"".join(kind + struct.pack(">I", 8 + len(data)) + data for kind, data in
                    ((kind, png(size)) for size, kind in types.items()))  # fmt: skip
    return b"icns" + struct.pack(">I", 8 + len(body)) + body


def write_icons(folder: Path) -> dict[str, Path]:
    """Write the PNG (256 px), ICO, and ICNS icons into folder; return them by suffix.

    The names carry a digest of the drawing: Windows caches a shortcut's icon by file path, so a changed
    icon needs a new path to show. Icons of earlier drawings in folder are removed.
    """
    import hashlib

    folder.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(svg().encode("utf-8")).hexdigest()[:8]
    files = {"png": png(256), "ico": ico(), "icns": icns()}
    out = {}
    for suffix, data in files.items():
        path = folder / f"groundcast-{digest}.{suffix}"
        path.write_bytes(data)
        out[suffix] = path
    for old in folder.glob("groundcast*.*"):
        if old.suffix.lstrip(".") in files and old not in out.values():
            old.unlink()
    return out


def banner(name: str, tagline: str, ink: str, muted: str, prefix: str = "gb") -> str:
    """A README banner: the icon beside the name and a tagline (fonts are the viewer's serif and sans)."""
    icon = svg(prefix).replace(' role="img" aria-label="Groundcast"', "").replace(
        "<svg ", '<svg x="6" y="6" width="108" height="108" ', 1)
    return "".join([
        f'<svg xmlns="http://www.w3.org/2000/svg" width="560" height="120" viewBox="0 0 560 120" role="img" '
        f'aria-label="{name}">',
        f"<title>{name}</title>",
        icon.rstrip("\n"),
        f'<text x="138" y="68" fill="{ink}" font-size="56" font-weight="600" letter-spacing="-1" '
        'font-family="Iowan Old Style, Palatino Linotype, Palatino, Book Antiqua, Georgia, serif">'
        f"{name}</text>",
        f'<text x="141" y="100" fill="{muted}" font-size="18" '
        'font-family="Segoe UI, -apple-system, Helvetica Neue, Arial, sans-serif">'
        f"{tagline}</text>",
        "</svg>\n",
    ])  # fmt: skip
