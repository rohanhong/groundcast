"""Minimal Office files for tests, written part by part (no Office library needed)."""

from __future__ import annotations

import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

_P_NS = (
    'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
    'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
)
_RELS_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_SLIDE_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide"
_NOTES_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/notesSlide"
_W_NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def _shape(paragraphs: list[str], placeholder: str | None = None) -> str:
    ph = f'<p:nvSpPr><p:cNvPr id="2" name="s"/><p:cNvSpPr/><p:nvPr><p:ph type="{placeholder}"/></p:nvPr></p:nvSpPr>' \
        if placeholder else '<p:nvSpPr><p:cNvPr id="2" name="s"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>'
    paras = "".join(f"<a:p><a:r><a:t>{escape(t)}</a:t></a:r></a:p>" for t in paragraphs)
    return f"<p:sp>{ph}<p:txBody><a:bodyPr/>{paras}</p:txBody></p:sp>"


def write_pptx(
    path: Path, slides: list[list[tuple[str | None, list[str]]]], notes: dict[int, str] | None = None,
    hidden: frozenset[int] = frozenset(),
) -> Path:
    """Each slide is a list of (placeholder type or None, paragraphs); notes by slide number."""
    notes = notes or {}
    with zipfile.ZipFile(path, "w") as z:
        ids = "".join(f'<p:sldId id="{256 + n}" r:id="rId{n}"/>' for n in range(1, len(slides) + 1))
        z.writestr("ppt/presentation.xml", f"<p:presentation {_P_NS}><p:sldIdLst>{ids}</p:sldIdLst></p:presentation>")
        rels = "".join(f'<Relationship Id="rId{n}" Type="{_SLIDE_REL}" Target="slides/slide{n}.xml"/>'
                       for n in range(1, len(slides) + 1))  # fmt: skip
        z.writestr("ppt/_rels/presentation.xml.rels", f'<Relationships xmlns="{_RELS_NS}">{rels}</Relationships>')
        for n, shapes in enumerate(slides, start=1):
            show = ' show="0"' if n in hidden else ""
            body = "".join(_shape(paras, ph) for ph, paras in shapes)
            # Number placeholders repeat on every slide and must be skipped.
            body += _shape([str(n)], "sldNum")
            z.writestr(f"ppt/slides/slide{n}.xml",
                       f"<p:sld {_P_NS}{show}><p:cSld><p:spTree>{body}</p:spTree></p:cSld></p:sld>")  # fmt: skip
            if n in notes:
                z.writestr(f"ppt/slides/_rels/slide{n}.xml.rels",
                           f'<Relationships xmlns="{_RELS_NS}"><Relationship Id="rId9" Type="{_NOTES_REL}" '
                           f'Target="../notesSlides/notesSlide{n}.xml"/></Relationships>')  # fmt: skip
                notes_body = _shape(["slide image"], "sldImg") + _shape([notes[n]], "body")
                z.writestr(f"ppt/notesSlides/notesSlide{n}.xml",
                           f"<p:notes {_P_NS}><p:cSld><p:spTree>{notes_body}</p:spTree></p:cSld></p:notes>")  # fmt: skip
    return path


def write_docx(path: Path, body_xml: str) -> Path:
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", f"<w:document {_W_NS}><w:body>{body_xml}</w:body></w:document>")
    return path


def w_par(text: str, page_break_before: bool = False, rendered_break: bool = False) -> str:
    brk = '<w:r><w:br w:type="page"/></w:r>' if page_break_before else ""
    rendered = "<w:lastRenderedPageBreak/>" if rendered_break else ""
    return f"<w:p>{brk}<w:r>{rendered}<w:t>{escape(text)}</w:t></w:r></w:p>"
