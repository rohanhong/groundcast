"""The groundcast logo as image files for shortcuts: PNG, Windows ICO, and macOS ICNS.

The logo is drawn here (the same shapes as web/static/favicon.svg) so no
binary image has to live in the repository. Shapes are in a 40-unit box;
each pixel is sampled several times for smooth edges.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

import numpy as np

BOX = 40.0
CORNER = 11.0
GRADIENT = ((0x0F, 0x76, 0x6E), (0xD9, 0x77, 0x06))  # top left to bottom right, as in favicon.svg
# White bars standing on a ground line: x, y, width, height, corner radius, opacity.
BARS = (
    (9.0, 17.0, 3.0, 11.0, 1.5, 1.0),
    (14.5, 11.0, 3.0, 17.0, 1.5, 1.0),
    (20.0, 14.0, 3.0, 14.0, 1.5, 1.0),
    (25.5, 19.0, 3.0, 9.0, 1.5, 1.0),
    (8.0, 30.0, 22.0, 2.4, 1.2, 0.75),
)
SAMPLES = 4  # per pixel side
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)
ICNS_TYPES = {128: b"ic07", 256: b"ic08", 512: b"ic09"}


def _rounded_rect(x: np.ndarray, y: np.ndarray, left: float, top: float, w: float, h: float, r: float) -> np.ndarray:
    cx, cy = left + w / 2, top + h / 2
    dx = np.maximum(np.abs(x - cx) - (w / 2 - r), 0.0)
    dy = np.maximum(np.abs(y - cy) - (h / 2 - r), 0.0)
    return (dx * dx + dy * dy <= r * r).astype(np.float32)


def render(size: int) -> np.ndarray:
    """RGBA pixels, shape (size, size, 4), uint8."""
    n = size * SAMPLES
    step = BOX / n
    coords = (np.arange(n, dtype=np.float32) + 0.5) * step
    x, y = np.meshgrid(coords, coords)
    shape = _rounded_rect(x, y, 0.0, 0.0, BOX, BOX, CORNER)
    t = ((x + y) / (2 * BOX))[..., None]
    start, end = (np.array(c, dtype=np.float32) for c in GRADIENT)
    rgb = start * (1 - t) + end * t
    for left, top, w, h, r, opacity in BARS:
        cover = (_rounded_rect(x, y, left, top, w, h, r) * opacity)[..., None]
        rgb = rgb * (1 - cover) + 255.0 * cover
    rgba = np.concatenate([rgb * shape[..., None], (shape * 255.0)[..., None]], axis=-1)
    # Average each block of samples into one pixel, colours weighted by coverage.
    blocks = rgba.reshape(size, SAMPLES, size, SAMPLES, 4).mean(axis=(1, 3))
    alpha = blocks[..., 3:4]
    colour = np.where(alpha > 0, blocks[..., :3] * 255.0 / np.maximum(alpha, 1e-6), 0.0)
    return np.clip(np.concatenate([colour, alpha], axis=-1) + 0.5, 0, 255).astype(np.uint8)


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
    """Write groundcast.png (256 px), .ico, and .icns into folder; return them by suffix."""
    folder.mkdir(parents=True, exist_ok=True)
    files = {"png": png(256), "ico": ico(), "icns": icns()}
    out = {}
    for suffix, data in files.items():
        path = folder / f"groundcast.{suffix}"
        path.write_bytes(data)
        out[suffix] = path
    return out
