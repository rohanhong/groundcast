"""The Groundcast brand: the mark, the wordmark, and their lockups, written out as SVG and as PNG, ICO, and ICNS.

The mark is a G drawn as sound waves: two open rings spread from a source at
the centre, and the G's crossbar is an amber ground line the source stands
on, as every sentence of a session stands on its sources. It is flat: cream
rings and an amber bar on a teal rounded square. Icons of SMALL_MAX pixels
and below drop the inner ring and grow the source, so the G stays legible at
16 px. All shapes are defined once below, in a unit box (0 to 1, y down);
`svg()` writes them as vector shapes and `render()` samples them several
times per pixel, so the two outputs match without any binary image in the
repository. The wordmark is the product name set in Fraunces, kept as
outlines in groundcast.wordmark, so it looks the same on every machine.

BRAND_FILES lists every committed file drawn here (assets/, the web app's
icons, the README banners), and RASTER_FILES the PNG renders of some of
them; `python -m groundcast.icon` rewrites both, and tests keep them the
same. Icon files carry `digest()` in their names, and
the page links the favicon with it, so a changed drawing is never shown from
an old cached copy.
"""

from __future__ import annotations

import hashlib
import math
import struct
import sys
import zlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from groundcast.wordmark import NAME, TAGLINE

CORNER = 0.225  # corner radius of the rounded square
CENTRE = (0.5, 0.5)
GAP = 40.0  # degrees: the G's opening, from straight right towards the top
TILE = "#0e3b3a"
CREAM = "#fff4e0"
AMBER = "#f0a23b"


@dataclass(frozen=True)
class Geometry:
    rings: tuple[tuple[float, float, float], ...]  # radius, stroke width, opacity; the outer ring first
    bar: float  # stroke width of the crossbar, which runs from the centre to the outer ring
    source: float  # radius of the source at the centre


LARGE = Geometry(rings=((0.27, 0.11, 1.0), (0.14, 0.06, 0.55)), bar=0.11, source=0.07)
SMALL = Geometry(rings=((0.27, 0.11, 1.0),), bar=0.11, source=0.095)
SMALL_MAX = 24  # px: icons this size and below use SMALL


@dataclass(frozen=True)
class Ground:
    mark: str  # rings and source
    bar: str
    text: str  # the wordmark
    muted: str  # the tagline


GROUNDS = {
    "light": Ground(mark="#0e3b3a", bar="#d98a1e", text="#0e3b3a", muted="#5b6d6a"),
    "dark": Ground(mark=CREAM, bar=AMBER, text=CREAM, muted="#a9b8b4"),
}

SAMPLES = 4  # per pixel side
ICO_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)  # window icon sizes at 100 to 200 % scaling
ICNS_TYPES = {128: b"ic07", 256: b"ic08", 512: b"ic09"}
SVG_BOX = 100.0


def geometry(size: int) -> Geometry:
    return SMALL if size <= SMALL_MAX else LARGE


def _rgb(hex_colour: str) -> np.ndarray:
    return np.array([int(hex_colour[i : i + 2], 16) for i in (1, 3, 5)], dtype=np.float32)


def ring_ends(radius: float) -> tuple[tuple[float, float], tuple[float, float]]:
    """Where a ring starts (at the top of the opening) and ends (straight right, on the crossbar)."""
    cx, cy = CENTRE
    a = math.radians(GAP)
    return (cx + radius * math.cos(a), cy - radius * math.sin(a)), (cx + radius, cy)


# Raster


def _paint(rgb: np.ndarray, colour: np.ndarray, cover: np.ndarray) -> np.ndarray:
    """Paint one colour with coverage 0 to 1 over an opaque picture."""
    c = cover[..., None]
    return rgb * (1 - c) + colour * c


def render(size: int) -> np.ndarray:
    """RGBA pixels of the icon on its tile, shape (size, size, 4), uint8."""
    g = geometry(size)
    n = size * SAMPLES
    coords = (np.arange(n, dtype=np.float32) + 0.5) / n
    x, y = np.meshgrid(coords, coords)
    cx, cy = CENTRE

    rgb = np.broadcast_to(_rgb(TILE), (n, n, 3)).copy()
    dx, dy = x - cx, y - cy
    angle = np.degrees(np.arctan2(dy, dx)) % 360.0  # 0 straight right, growing clockwise on screen
    for radius, width, opacity in g.rings:
        (sx, sy), (ex, ey) = ring_ends(radius)
        to_ends = np.minimum(np.hypot(x - sx, y - sy), np.hypot(x - ex, y - ey))
        d = np.where(angle <= 360.0 - GAP, np.abs(np.hypot(dx, dy) - radius), to_ends)
        rgb = _paint(rgb, _rgb(CREAM), opacity * (d <= width / 2))

    length = g.rings[0][0]
    t = np.clip((x - cx) / length, 0.0, 1.0)
    bar = np.hypot(x - (cx + t * length), y - cy) <= g.bar / 2
    rgb = _paint(rgb, _rgb(AMBER), bar.astype(np.float32))
    rgb = _paint(rgb, _rgb(CREAM), (np.hypot(dx, dy) <= g.source).astype(np.float32))

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


def _f(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _n(value: float) -> str:
    return _f(value * SVG_BOX)


def _glyph(g: Geometry, mark: str, bar: str) -> str:
    """The mark's shapes, without the tile, in a box of SVG_BOX units."""
    cx, cy = CENTRE
    out = []
    for radius, width, opacity in g.rings:
        (sx, sy), (ex, ey) = ring_ends(radius)
        alpha = "" if opacity == 1 else f' stroke-opacity="{opacity:g}"'
        out.append(f'<path d="M{_n(sx)} {_n(sy)}A{_n(radius)} {_n(radius)} 0 1 0 {_n(ex)} {_n(ey)}" fill="none" '
                   f'stroke="{mark}" stroke-width="{_n(width)}" stroke-linecap="round"{alpha}/>')  # fmt: skip
    out.append(f'<path d="M{_n(cx)} {_n(cy)}H{_n(cx + g.rings[0][0])}" stroke="{bar}" stroke-width="{_n(g.bar)}" '
               'stroke-linecap="round"/>')  # fmt: skip
    out.append(f'<circle cx="{_n(cx)}" cy="{_n(cy)}" r="{_n(g.source)}" fill="{mark}"/>')
    return "".join(out)


def _tile(g: Geometry) -> str:
    box = _n(1)
    return f'<rect width="{box}" height="{box}" rx="{_n(CORNER)}" fill="{TILE}"/>' + _glyph(g, CREAM, AMBER)


def _place(content: str, x: float, y: float, side: float) -> str:
    """Content drawn in the SVG_BOX box, moved to (x, y) and scaled to side units."""
    return f'<g transform="translate({_f(x)} {_f(y)}) scale({side / SVG_BOX:.6g})">{content}</g>'


def _text(outline: dict, x: float, baseline: float, cap: float, colour: str) -> str:
    """An outline from groundcast.wordmark with its ink starting at x, scaled so a capital is cap tall."""
    s = cap / outline["cap"]
    return (f'<path transform="translate({_f(x - outline["box"][0] * s)} {_f(baseline)}) scale({s:.6g})" '
            f'fill="{colour}" d="{outline["path"]}"/>')  # fmt: skip


def _extent(outline: dict, cap: float) -> tuple[float, float, float]:
    """Ink width, height above the baseline, and depth below it, for a capital cap tall."""
    s = cap / outline["cap"]
    x0, y0, x1, y1 = outline["box"]
    return (x1 - x0) * s, -y0 * s, max(y1, 0) * s


def _document(width: float, height: float, body: str, sized: bool = True) -> str:
    size = f' width="{_f(width)}" height="{_f(height)}"' if sized else ""
    return (f'<svg xmlns="http://www.w3.org/2000/svg"{size} viewBox="0 0 {_f(width)} {_f(height)}" role="img" '
            f'aria-label="Groundcast"><title>Groundcast</title>{body}</svg>\n')  # fmt: skip


def svg(small: bool = False) -> str:
    """The icon on its tile as an SVG document; small is the version for 24 px and below."""
    return _document(SVG_BOX, SVG_BOX, _tile(SMALL if small else LARGE), sized=False)


def glyph(ground: str) -> str:
    """The mark without its tile, in the colours for a light or dark ground."""
    c = GROUNDS[ground]
    inset = CENTRE[0] - LARGE.rings[0][0] - LARGE.rings[0][1] / 2 - 0.025
    side = (1 - 2 * inset) * SVG_BOX
    body = f'<g transform="translate({_n(-inset)} {_n(-inset)})">{_glyph(LARGE, c.mark, c.bar)}</g>'
    return _document(side, side, body)


def wordmark(ground: str, cap: float = 100.0) -> str:
    """The product name alone."""
    width, above, below = _extent(NAME, cap)
    return _document(width, above + below, _text(NAME, 0, above, cap, GROUNDS[ground].text))


def lockup(ground: str) -> str:
    """The icon beside the name, whose capitals are half the icon's height and centred on it."""
    side, cap = 100.0, 50.0
    x = side * 1.3
    width, _, _ = _extent(NAME, cap)
    body = _place(_tile(LARGE), 0, 0, side) + _text(NAME, x, (side + cap) / 2, cap, GROUNDS[ground].text)
    return _document(x + width, side, body)


def lockup_stacked(ground: str) -> str:
    """The icon centred above the name."""
    side, cap = 100.0, 30.0
    width, above, below = _extent(NAME, cap)
    total = max(side, width)
    baseline = side * 1.22 + above
    body = _place(_tile(LARGE), (total - side) / 2, 0, side) + _text(
        NAME, (total - width) / 2, baseline, cap, GROUNDS[ground].text)
    return _document(total, baseline + below, body)


def banner(ground: str) -> str:
    """The README banner: the icon beside the name and the tagline."""
    c = GROUNDS[ground]
    side, margin, x = 108.0, 6.0, 138.0
    name_cap, tagline_cap = 40.0, 13.0
    width = max(_extent(NAME, name_cap)[0], _extent(TAGLINE, tagline_cap)[0])
    body = (_place(_tile(LARGE), margin, margin, side) + _text(NAME, x, 62, name_cap, c.text)
            + _text(TAGLINE, x + 1, 96, tagline_cap, c.muted))  # fmt: skip
    return _document(x + width + margin, side + 2 * margin, body)


def social_preview() -> str:
    """A 1280 x 640 card for link previews: the mark, then the name standing on the crossbar's ground line."""
    c = GROUNDS["dark"]
    width, height, side = 1280.0, 640.0, 360.0
    cy = height / 2
    left = 520.0
    body = "".join([
        f'<rect width="{_f(width)}" height="{_f(height)}" fill="{TILE}"/>',
        _place(_glyph(LARGE, c.mark, c.bar), 330 - side / 2, cy - side / 2, side),
        f'<path d="M{_f(left - 20)} {_f(cy)}H{_f(width)}" stroke="{c.bar}" stroke-width="4" stroke-opacity=".85"/>',
        _text(NAME, left, cy - 26, 80, c.text),
        _text(TAGLINE, left + 2, cy + 48, 22, c.muted),
    ])  # fmt: skip
    return _document(width, height, body)


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


def digest() -> str:
    """A short digest of the drawing, which changes whenever the icon does."""
    return hashlib.sha256((svg() + svg(small=True)).encode("utf-8")).hexdigest()[:8]


ICON_MAKERS = {"png": lambda: png(256), "ico": ico, "icns": icns}


def icon_file(folder: Path, suffix: str) -> Path:
    """The icon file of the current drawing in folder, written when it is missing; other files stay."""
    path = folder / f"groundcast-{digest()}.{suffix}"
    if not path.is_file():
        folder.mkdir(parents=True, exist_ok=True)
        path.write_bytes(ICON_MAKERS[suffix]())
    return path


def write_icons(folder: Path) -> dict[str, Path]:
    """Write the PNG (256 px), ICO, and ICNS icons into folder; return them by suffix.

    The names carry a digest of the drawing: Windows caches a shortcut's icon by file path, so a changed
    icon needs a new path to show. Icons of earlier drawings in folder are removed.
    """
    folder.mkdir(parents=True, exist_ok=True)
    files = {suffix: make() for suffix, make in ICON_MAKERS.items()}
    out = {}
    for suffix, data in files.items():
        path = folder / f"groundcast-{digest()}.{suffix}"
        path.write_bytes(data)
        out[suffix] = path
    for old in folder.glob("groundcast*.*"):
        if old.suffix.lstrip(".") in files and old not in out.values():
            old.unlink()
    return out


# Committed files drawn here, by path from the repository root.
BRAND_FILES: dict[str, Callable[[], str]] = {
    "assets/mark.svg": svg,
    "assets/mark-small.svg": lambda: svg(small=True),
    "assets/glyph-on-light.svg": lambda: glyph("light"),
    "assets/glyph-on-dark.svg": lambda: glyph("dark"),
    "assets/wordmark-on-light.svg": lambda: wordmark("light"),
    "assets/wordmark-on-dark.svg": lambda: wordmark("dark"),
    "assets/lockup-on-light.svg": lambda: lockup("light"),
    "assets/lockup-on-dark.svg": lambda: lockup("dark"),
    "assets/lockup-stacked-on-light.svg": lambda: lockup_stacked("light"),
    "assets/lockup-stacked-on-dark.svg": lambda: lockup_stacked("dark"),
    "assets/social-preview.svg": social_preview,
    "src/groundcast/web/static/favicon.svg": lambda: svg(small=True),
    "src/groundcast/web/static/logo.svg": svg,
    "src/groundcast/web/static/wordmark.svg": lambda: wordmark("light"),
    ".github/assets/banner-light.svg": lambda: banner("light"),
    ".github/assets/banner-dark.svg": lambda: banner("dark"),
}


def write_brand_files(root: Path) -> list[Path]:
    """Rewrite the files in BRAND_FILES under root that differ from the drawing; return those written."""
    written = []
    for name, make in BRAND_FILES.items():
        path, text = root / name, make()
        if not path.is_file() or path.read_text(encoding="utf-8") != text:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8", newline="\n")
            written.append(path)
    return written


# Committed PNG renders of files in BRAND_FILES, for places that take no SVG (GitHub's social preview).
# Each records the SHA-256 of its source in a tEXt chunk, so a test spots a stale render without
# rendering; writing them needs resvg-py (the dev extra), since the text outlines are paths.
RASTER_FILES: dict[str, str] = {"assets/social-preview.png": "assets/social-preview.svg"}
SOURCE_KEY = b"Source-SHA256"


def source_sha256(name: str) -> str:
    """The SHA-256 of the drawing a raster file in RASTER_FILES is rendered from."""
    return hashlib.sha256(BRAND_FILES[RASTER_FILES[name]]().encode("utf-8")).hexdigest()


def png_text(data: bytes) -> dict[bytes, bytes]:
    """The tEXt entries of a PNG, by keyword."""
    out, pos = {}, 8
    while pos + 8 <= len(data):
        length, kind = struct.unpack(">I4s", data[pos : pos + 8])
        if kind == b"tEXt":
            keyword, _, value = data[pos + 8 : pos + 8 + length].partition(b"\x00")
            out[keyword] = value
        pos += 12 + length
    return out


def _with_text(data: bytes, keyword: bytes, value: bytes) -> bytes:
    """data with a tEXt entry added after its IHDR chunk."""
    body = keyword + b"\x00" + value
    entry = struct.pack(">I", len(body)) + b"tEXt" + body + struct.pack(">I", zlib.crc32(b"tEXt" + body) & 0xFFFFFFFF)
    end = 8 + 12 + struct.unpack(">I", data[8:12])[0]
    return data[:end] + entry + data[end:]


def write_raster_files(root: Path) -> tuple[list[Path], list[Path]]:
    """Render the files in RASTER_FILES under root whose recorded source differs; return those written and
    those left stale because resvg-py is not installed."""
    written, stale = [], []
    for name, source in RASTER_FILES.items():
        path, sha = root / name, source_sha256(name)
        if path.is_file() and png_text(path.read_bytes()).get(SOURCE_KEY) == sha.encode("ascii"):
            continue
        try:
            import resvg_py
        except ImportError:
            stale.append(path)
            continue
        data = resvg_py.svg_to_bytes(svg_string=BRAND_FILES[source](), skip_system_fonts=True)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(_with_text(data, SOURCE_KEY, sha.encode("ascii")))
        written.append(path)
    return written, stale


if __name__ == "__main__":
    # python -m groundcast.icon [repository root, default: the current directory]
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
    rendered, stale = write_raster_files(root)
    for path in write_brand_files(root) + rendered:
        print(f"wrote {path}")
    for path in stale:
        print(f"not rendered, install resvg-py (the dev extra): {path}", file=sys.stderr)
    sys.exit(1 if stale else 0)
