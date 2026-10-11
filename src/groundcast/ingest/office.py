"""PowerPoint and Word text, read straight from the Office Open XML parts.

A .pptx or .docx file is a zip archive of XML parts, so the standard library
reads them without another dependency. PowerPoint gives one page per slide
(locator s<slide>); Word has no fixed pages, so page numbers come from the
page breaks Word records when it saves a file: explicit breaks and the
breaks it last rendered. A file without them is a single page.
"""

from __future__ import annotations

import posixpath
import re
import zipfile
from collections.abc import Iterator
from pathlib import Path
from xml.etree import ElementTree as ET

from groundcast.ingest.units import ExtractionError, Unit, table_text

_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_MC_FALLBACK = "{http://schemas.openxmlformats.org/markup-compatibility/2006}Fallback"
_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}Relationship"
_NOTES_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/notesSlide"
# Placeholders that repeat on every slide and say nothing about the subject.
_SKIPPED_PLACEHOLDERS = frozenset({"sldNum", "dt", "ftr", "hdr", "sldImg"})
_END_PUNCTUATION = (".", "!", "?", ":", ";")
_SPACES = re.compile(r"\s+")


def _clean(text: str) -> str:
    return _SPACES.sub(" ", text).strip()


def _join_lines(lines: list[str]) -> str:
    """Join bullet-like lines into one block, ending each with a full stop if it has none."""
    out = []
    for line in lines:
        line = _clean(line)
        if line:
            out.append(line if line.endswith(_END_PUNCTUATION) else line + ".")
    return " ".join(out)


def _walk(node: ET.Element) -> Iterator[ET.Element]:
    """Elements in document order, skipping the fallback copies of alternate content."""
    for child in node:
        if child.tag == _MC_FALLBACK:
            continue
        yield child
        yield from _walk(child)


def _read_xml(archive: zipfile.ZipFile, name: str) -> ET.Element:
    try:
        return ET.fromstring(archive.read(name))
    except KeyError as exc:
        raise ExtractionError(f"missing part {name}; the file may be damaged") from exc
    except ET.ParseError as exc:
        raise ExtractionError(f"unreadable part {name}: {exc}") from exc


def _relationships(archive: zipfile.ZipFile, part: str) -> dict[str, tuple[str, str]]:
    """Relationship ID -> (type, target part name) for a part."""
    folder, name = posixpath.split(part)
    rels_name = posixpath.join(folder, "_rels", name + ".rels")
    if rels_name not in archive.namelist():
        return {}
    out = {}
    for rel in _read_xml(archive, rels_name).iter(_REL):
        target = rel.get("Target", "")
        if rel.get("TargetMode") == "External":
            continue
        out[rel.get("Id", "")] = (rel.get("Type", ""), posixpath.normpath(posixpath.join(folder, target)))
    return out


def _open(path: Path) -> zipfile.ZipFile:
    try:
        return zipfile.ZipFile(path)
    except zipfile.BadZipFile as exc:
        raise ExtractionError(f"{path.name} is not an Office Open XML file") from exc


# PowerPoint


def _paragraph_text(paragraph: ET.Element) -> str:
    parts = []
    for el in _walk(paragraph):
        if el.tag == _A + "t" and el.text:
            parts.append(el.text)
        elif el.tag == _A + "br":
            parts.append(" ")
    return "".join(parts)


def _shape_blocks(tree: ET.Element, keep_placeholder: frozenset[str] | None = None) -> list[str]:
    """One block per text box and per table row, in reading order of the XML."""
    blocks: list[str] = []
    for shape in _walk(tree):
        if shape.tag == _P + "sp":
            ph = shape.find(f"{_P}nvSpPr/{_P}nvPr/{_P}ph")
            ph_type = ph.get("type", "body") if ph is not None else ""
            if ph_type in _SKIPPED_PLACEHOLDERS:
                continue
            if keep_placeholder is not None and ph_type not in keep_placeholder:
                continue
            body = shape.find(f"{_P}txBody")
            if body is not None:
                lines = [_paragraph_text(p) for p in body.iter(_A + "p")]
                # A title stays a heading, so chunking folds it into the slide's text.
                title = ph_type in ("title", "ctrTitle")
                block = _clean(" ".join(lines)) if title else _join_lines(lines)
                if block:
                    blocks.append(block)
        elif shape.tag == _A + "tbl":
            rows = [[" ".join(_paragraph_text(p) for p in tc.iter(_A + "p")) for tc in tr.iter(_A + "tc")]
                    for tr in shape.iter(_A + "tr")]  # fmt: skip
            block = table_text(rows)
            if block:
                blocks.append(block)
    return blocks


def pptx_units(path: Path, notes: bool) -> list[Unit]:
    """One unit per visible slide, numbered as PowerPoint numbers them."""
    with _open(path) as archive:
        presentation = "ppt/presentation.xml"
        rels = _relationships(archive, presentation)
        units = []
        slide_ids = _read_xml(archive, presentation).iter(_P + "sldId")
        for number, sld in enumerate(slide_ids, start=1):
            rel = rels.get(sld.get(_R + "id", ""))
            if rel is None:
                continue
            slide_part = rel[1]
            slide = _read_xml(archive, slide_part)
            if slide.get("show") == "0":
                continue  # hidden slide
            blocks = _shape_blocks(slide)
            if notes:
                for rel_type, target in _relationships(archive, slide_part).values():
                    if rel_type == _NOTES_TYPE:
                        text = " ".join(_shape_blocks(_read_xml(archive, target), frozenset({"body"})))
                        if text:
                            blocks.append(f"Speaker notes: {text}")
            units.append(Unit(f"s{number}", blocks))
        return units


# Word


class _Pages:
    """Collects paragraph blocks page by page while walking a Word document."""

    def __init__(self) -> None:
        self.pages: list[list[str]] = [[]]
        self.current: list[str] = []

    def text(self, value: str) -> None:
        self.current.append(value)

    def end_block(self) -> None:
        block = _clean("".join(self.current))
        if block:
            self.pages[-1].append(block)
        self.current = []

    def page_break(self) -> None:
        self.end_block()
        if self.pages[-1]:
            self.pages.append([])


def _docx_paragraph(paragraph: ET.Element, pages: _Pages) -> None:
    for el in _walk(paragraph):
        tag = el.tag
        if tag == _W + "t" and el.text:
            pages.text(el.text)
        elif tag in (_W + "tab", _W + "cr"):
            pages.text(" ")
        elif tag == _W + "br":
            if el.get(_W + "type") == "page":
                pages.page_break()
            else:
                pages.text(" ")
        elif tag == _W + "lastRenderedPageBreak":
            pages.page_break()
    pages.end_block()


def docx_units(path: Path) -> list[Unit]:
    with _open(path) as archive:
        body = _read_xml(archive, "word/document.xml").find(_W + "body")
    if body is None:
        raise ExtractionError(f"{path.name} has no document body")
    pages = _Pages()
    for el in body:
        if el.tag == _W + "p":
            _docx_paragraph(el, pages)
        elif el.tag == _W + "tbl":
            rows = []
            for row in el.iter(_W + "tr"):
                cells = []
                for cell in row.iter(_W + "tc"):
                    cell_pages = _Pages()
                    for p in cell.iter(_W + "p"):
                        _docx_paragraph(p, cell_pages)
                    cells.append(" ".join(b for page in cell_pages.pages for b in page))
                rows.append(cells)
            text = table_text(rows)
            if text:
                pages.end_block()
                pages.text(text)
                pages.end_block()
    pages.end_block()
    page_list = [p for p in pages.pages if p] or [[]]
    return [Unit(f"p{n}", blocks) for n, blocks in enumerate(page_list, start=1)]
