# Groundcast brand assets

Every file in this folder is drawn by `src/groundcast/icon.py`. Do not edit
them by hand: change the drawing there, then run `python -m groundcast.icon`
from the repository root, which also rewrites the web app's icons and the
README banners. A test fails when a committed file differs from the drawing.
The one PNG, `social-preview.png`, is rendered from its SVG with resvg-py
(in the `dev` extra); it records the SVG's SHA-256 in a `Source-SHA256`
text chunk, which the test compares, and the command exits non-zero when it
is stale and resvg-py is missing.

## The mark

A G drawn as sound waves. Two open rings spread from a source at the centre,
and the G's crossbar is an amber ground line the source stands on, as every
sentence of a session stands on its sources.

Construction, in a unit box (0 to 1, y down), centre at (0.5, 0.5):

| Part | Large (above 24 px) | Small (24 px and below) |
| --- | --- | --- |
| Outer ring | radius 0.27, stroke 0.11 | radius 0.27, stroke 0.11 |
| Inner ring | radius 0.14, stroke 0.06, 55 % opacity | none |
| Crossbar | centre to the outer ring, stroke 0.11 | the same |
| Source | radius 0.07 | radius 0.095 |
| Opening | 40 degrees, from straight right towards the top | the same |
| Tile | rounded square, corner radius 0.225 | the same |

The small drawing keeps the G legible in a browser tab. The ICO and the
favicon use it at 24 px and below, the large drawing above.

## Files

| File | Use |
| --- | --- |
| `mark.svg` | The app icon: the mark on its tile. Any size above 24 px. |
| `mark-small.svg` | The app icon at 24 px and below. |
| `glyph-on-light.svg`, `glyph-on-dark.svg` | The mark without its tile, for a light or dark ground. |
| `wordmark-on-light.svg`, `wordmark-on-dark.svg` | The name alone. |
| `lockup-on-light.svg`, `lockup-on-dark.svg` | Icon beside the name; the default signature. |
| `lockup-stacked-on-light.svg`, `lockup-stacked-on-dark.svg` | Icon above the name, for square spaces. |
| `social-preview.svg` | 1280 x 640 link preview card. |
| `social-preview.png` | The same card as PNG, for GitHub's social preview. |

Also drawn from the same source: `src/groundcast/web/static/favicon.svg`,
`logo.svg`, and `wordmark.svg` (the sidebar paints it as a mask in the
theme's colour), `.github/assets/banner-light.svg` and `banner-dark.svg`
(the README header), and the PNG, ICO, and ICNS shortcut icons, which
`groundcast shortcut` renders into the data directory.

GitHub accepts only PNG, JPG, or GIF as a social preview and does not read
it from the repository: upload `social-preview.png` in the repository's
Settings, General, Social preview, again whenever it changes.

## Colour

| Name | Hex | Use |
| --- | --- | --- |
| Teal | `#0e3b3a` | The tile; the mark and name on light grounds |
| Cream | `#fff4e0` | Rings and source on the tile; the mark and name on dark grounds |
| Amber | `#f0a23b` | The crossbar on the tile and on dark grounds; the card's ground line |
| Amber on light | `#d98a1e` | The crossbar on light grounds |
| Muted on light | `#5b6d6a` | The tagline on light grounds |
| Muted on dark | `#a9b8b4` | The tagline on dark grounds |

The web app keeps its own interface palette in
`src/groundcast/web/static/style.css`, in the same teal and amber hues; its
`--wordmark` token uses Teal and Cream.

## Typography

The name is set in Fraunces at weight 600, optical size 72, SOFT 0, WONK 0,
with kerning and a tracking of -20 units per 2000 (-1 %). The tagline is
Fraunces at weight 400, optical size 24. Both are stored as outlines in
`src/groundcast/wordmark.py`, so they look the same on every machine and no
font file is in the repository. To change the text or the settings, run
`scripts/outline_wordmark.py` with the Fraunces variable font (see its
docstring), then `python -m groundcast.icon`.

Fraunces is by the Fraunces Project Authors under the SIL Open Font License
1.1 (https://github.com/undercasetype/Fraunces). The outlines here are
artwork made with the font, not the font itself.

## Use

- Clear space: keep free space of at least half the icon's height around the
  icon and the lockups (the height of a capital, for the wordmark alone).
- Minimum size: the icon at 16 px, the horizontal lockup at 120 px wide, the
  wordmark at 80 px wide.
- Use the `-on-light` files on light grounds and the `-on-dark` files on
  dark ones; on photographs or busy grounds use the icon on its tile.
- Write the name as Groundcast, with a capital G.
- Do not recolour, stretch, rotate, or outline the mark; do not add
  gradients, shadows, or glows; do not rearrange or respace a lockup; do
  not set the name in another typeface; do not use the large drawing at
  24 px or below.
