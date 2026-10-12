"""Where a chunk is, in words and as a link (page, slide, or timestamp).

A PDF opens at its page (#page=N) and a recording at its moment (#t=S),
since browsers support both. Other files cannot be opened at a place, so
each material also gets a text view, <id>.view.html next to the original:
the extracted text with an anchor per page, slide, or passage, and a link
to the original. Links work from disk and from the app alike.
"""

from __future__ import annotations

from collections.abc import Iterable
from html import escape
from itertools import groupby

from groundcast.models import Chunk, Material

VIEW_SUFFIX = ".view.html"
MEDIA_KINDS = frozenset({"video", "audio"})

_STYLE = """
:root { --fg: #1d1f23; --muted: #5d6470; --bg: #ffffff; --accent: #3b5bdb; --mark: #fff3bf; --warn: #b54708; }
@media (prefers-color-scheme: dark) {
  :root { --fg: #e6e8eb; --muted: #9aa3ae; --bg: #15171a; --accent: #8ea6ff; --mark: #4a3f10; --warn: #f5a35c; }
}
body { font: 17px/1.6 system-ui, sans-serif; color: var(--fg); background: var(--bg);
       max-width: 46rem; margin: 0 auto; padding: 1.5rem 1rem 4rem; }
h1 { font-size: 1.5rem; } h2 { font-size: 1.05rem; margin-top: 1.6rem; color: var(--muted); }
a { color: var(--accent); }
.meta { color: var(--muted); font-size: .9rem; }
p:target, section:target h2 { background: var(--mark); }
.id { color: var(--muted); font-size: .75rem; margin-right: .4rem; }
.low { color: var(--warn); font-size: .8rem; }
"""


def clock(seconds: int) -> str:
    """12:34, or 1:02:03 past an hour."""
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def view_name(material: Material) -> str:
    return f"{material.id}{VIEW_SUFFIX}"


def anchor(chunk: Chunk) -> str:
    return f"{chunk.locator}-{chunk.index}"


def place(locator: str, material: Material) -> str:
    """The page, slide, or moment a locator names, or "" when the file has no such places."""
    kind, number = locator[:1], locator[1:]
    if kind == "s":
        return f"slide {number}"
    if kind == "t":
        return clock(int(number))
    if kind == "p" and (material.kind == "pdf" or material.pages > 1):
        return f"page {number}"
    return ""


def chunk_label(chunk: Chunk, material: Material) -> str:
    """File name plus where the chunk is, for example "deck.pptx, slide 3, passage 2"."""
    where = place(chunk.locator, material)
    if material.kind in MEDIA_KINDS:
        return f"{material.filename}, at {where}"
    return ", ".join(x for x in (material.filename, where, f"passage {chunk.index}") if x)


def original_path(locator: str, material: Material) -> str:
    """The original file at the locator's page or moment, where browsers support it."""
    path = f"materials/{material.stored_name}"
    if material.kind == "pdf" and locator.startswith("p"):
        return f"{path}#page={locator[1:]}"
    if material.kind in MEDIA_KINDS and locator.startswith("t"):
        return f"{path}#t={locator[1:]}"
    return path


def material_path(chunk: Chunk, material: Material) -> str:
    """Where a source link for this chunk points, relative to the data directory."""
    if material.kind == "pdf" or material.kind in MEDIA_KINDS or (material.kind == "image" and material.pages == 1):
        return original_path(chunk.locator, material)
    return f"materials/{view_name(material)}#{anchor(chunk)}"


def render_view(material: Material, chunks: Iterable[Chunk], review_below: float | None = None) -> str:
    """The material's text, one section per page, slide, or passage."""
    title = escape(material.filename)
    meta = [f"{escape(material.kind)}, {material.words} words"]
    if material.source_url:
        fetched = material.fetched_at.strftime("%Y-%m-%d") if material.fetched_at else "unknown date"
        meta.append(f'from <a href="{escape(material.source_url)}">{escape(material.source_url)}</a>, '
                    f"fetched {fetched}")  # fmt: skip
    reviewed = f", checked by you on {material.reviewed_at:%Y-%m-%d}" if material.reviewed_at else ", not checked yet"
    if material.kind in MEDIA_KINDS:
        meta.append(f"recognised speech{reviewed}")
    elif material.kind == "image":
        meta.append(f"recognised text{reviewed}")
    elif material.ocr_pages:
        pages = ", ".join(map(str, material.ocr_pages))
        meta.append(f"text recognised from the page image on page(s) {pages}{reviewed}")
    parts = [
        "<!doctype html>",
        # No machine translation: a translated sentence is no longer the text the sources were checked against.
        '<html lang="en" translate="no"><head><meta charset="utf-8"><meta name="google" content="notranslate">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{title}</title><style>{_STYLE}</style></head><body>",
        f"<h1>{title}</h1>",
        f'<p class="meta">{"; ".join(meta)}. <a href="{escape(material.stored_name)}">Open the original</a></p>',
    ]
    for locator, group in groupby(chunks, key=lambda c: c.locator):
        where = place(locator, material) or "Text"
        heading = escape(where[:1].upper() + where[1:])
        original = original_path(locator, material)
        if original != f"materials/{material.stored_name}":
            heading = f'<a href="{escape(original.removeprefix("materials/"))}">{heading}</a>'
        parts.append(f'<section id="{escape(locator)}"><h2>{heading}</h2>')
        for chunk in group:
            low = ""
            if chunk.uncertain:
                low = f' <span class="low">(check: {escape(", ".join(chunk.uncertain))})</span>'
            if review_below is not None and chunk.confidence is not None and chunk.confidence < review_below:
                low = f' <span class="low">(recognised with low confidence: {chunk.confidence:.2f})</span>'
            parts.append(f'<p id="{escape(anchor(chunk))}"><span class="id">{escape(chunk.id)}</span>'
                         f"{escape(chunk.text)}{low}</p>")  # fmt: skip
        parts.append("</section>")
    parts.append("</body></html>")
    return "\n".join(parts)
