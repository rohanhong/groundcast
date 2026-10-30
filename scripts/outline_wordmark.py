"""Write src/groundcast/wordmark.py: the product name and tagline as outlines, so no font is needed to show them.

Usage: python scripts/outline_wordmark.py <Fraunces variable font .ttf> [--out PATH]

The font is not part of the repository: download Fraunces[SOFT,WONK,opsz,wght].ttf from
https://github.com/undercasetype/Fraunces (SIL Open Font License 1.1). Needs `pip install uharfbuzz
fonttools` (only for this script). The text is shaped with kerning, drawn at the instance given by
--name-axes and --tagline-axes, and written in font units, y down, baseline at 0, rounded to whole units.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import uharfbuzz as hb
from fontTools.pens.basePen import BasePen

ROOT = Path(__file__).resolve().parent.parent
LINE = 96  # characters of path data per source line


class PathPen(BasePen):
    """Collects one glyph as SVG path data, shifted right by dx, with its bounds."""

    def __init__(self, dx: float, box: list[float]) -> None:
        super().__init__(None)
        self.dx, self.box, self.out = dx, box, []

    def _p(self, pt: tuple[float, float]) -> str:
        x, y = round(pt[0] + self.dx), round(-pt[1])
        self.box[:] = [min(self.box[0], x), min(self.box[1], y), max(self.box[2], x), max(self.box[3], y)]
        return f"{x} {y}"

    def _moveTo(self, pt):  # noqa: N802 (fontTools pen protocol)
        self.out.append("M" + self._p(pt))

    def _lineTo(self, pt):  # noqa: N802
        self.out.append("L" + self._p(pt))

    def _curveToOne(self, a, b, c):  # noqa: N802
        self.out.append("C" + " ".join(self._p(p) for p in (a, b, c)))

    def _qCurveToOne(self, a, b):  # noqa: N802
        self.out.append("Q" + " ".join(self._p(p) for p in (a, b)))

    def _closePath(self):  # noqa: N802
        self.out.append("Z")


def outline(font_path: Path, text: str, axes: str, tracking: int) -> dict:
    face = hb.Face(hb.Blob.from_file_path(str(font_path)))
    font = hb.Font(face)
    font.set_variations({k: float(v) for k, v in (kv.split("=") for kv in axes.split(","))})
    buf = hb.Buffer()
    buf.add_str(text)
    buf.guess_segment_properties()
    hb.shape(font, buf, {"kern": True, "liga": False})
    x, parts, box = 0, [], [float("inf"), float("inf"), float("-inf"), float("-inf")]
    for info, pos in zip(buf.glyph_infos, buf.glyph_positions):
        pen = PathPen(x + pos.x_offset, box)
        font.draw_glyph_with_pen(info.codepoint, pen)
        parts.append("".join(pen.out))
        x += pos.x_advance + tracking
    cap = font.get_glyph_extents(font.get_nominal_glyph(ord("H"))).y_bearing  # y up in HarfBuzz
    return {"text": text, "axes": axes, "tracking": tracking, "upm": face.upem, "cap": cap,
            "advance": x - tracking, "box": tuple(int(v) for v in box), "path": "".join(parts)}


def module(name: dict, tagline: dict) -> str:
    def entry(var: str, data: dict) -> str:
        path = data["path"]
        lines = [f"    {path[i:i + LINE]!r}" for i in range(0, len(path), LINE)]
        fields = "".join(f"    {k!r}: {data[k]!r},\n" for k in ("text", "axes", "tracking", "upm", "cap", "advance", "box"))
        return f"{var} = {{\n{fields}    'path': (\n" + "\n".join("    " + line for line in lines) + "\n    ),\n}\n"

    return (
        '"""The Groundcast wordmark and tagline as outlines; written by scripts/outline_wordmark.py, do not edit.\n\n'
        "Set in Fraunces (SIL Open Font License 1.1, https://github.com/undercasetype/Fraunces) at the axes\n"
        "given, with kerning; tracking is added between letters. Units are the font's (upm per em), y down,\n"
        "baseline at 0; box is the outline's bounds (x0, y0, x1, y1) and cap the height of a capital.\n"
        '"""\n\n# fmt: off\n' + entry("NAME", name) + "\n" + entry("TAGLINE", tagline) + "# fmt: on\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("font", type=Path, help="Fraunces variable font (.ttf)")
    parser.add_argument("--out", type=Path, default=ROOT / "src/groundcast/wordmark.py")
    parser.add_argument("--name", default="Groundcast")
    parser.add_argument("--name-axes", default="wght=600,opsz=72,SOFT=0,WONK=0")
    parser.add_argument("--name-tracking", type=int, default=-20, help="font units between letters")
    parser.add_argument("--tagline", default="Study audio, grounded in your materials")
    parser.add_argument("--tagline-axes", default="wght=400,opsz=24,SOFT=0,WONK=0")
    parser.add_argument("--tagline-tracking", type=int, default=0)
    args = parser.parse_args()
    name = outline(args.font, args.name, args.name_axes, args.name_tracking)
    tagline = outline(args.font, args.tagline, args.tagline_axes, args.tagline_tracking)
    args.out.write_text(module(name, tagline), encoding="utf-8", newline="\n")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
