"""Text extraction: file -> units (pages, slides, passages) -> paragraph blocks.

PDF text comes from poppler's pdftotext, run as a separate program (GPL).
Markdown, plain text, and web pages have no pages and count as one page.
PowerPoint and Word files are read by groundcast.ingest.office, web pages by
groundcast.ingest.web; video and audio go through speech recognition
(groundcast.ingest.asr), which is slow and runs apart from this module.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from groundcast.config import Settings
from groundcast.ingest.office import docx_units, pptx_units
from groundcast.ingest.units import ExtractionError, Unit
from groundcast.ingest.web import decode_html, html_units

KIND_BY_SUFFIX = {
    ".pdf": "pdf",
    ".md": "markdown",
    ".markdown": "markdown",
    ".txt": "text",
    ".pptx": "pptx",
    ".docx": "docx",
    ".html": "html",
    ".htm": "html",
    ".mp4": "video",
    ".mkv": "video",
    ".webm": "video",
    ".mov": "video",
    ".m4v": "video",
    ".avi": "video",
    ".mp3": "audio",
    ".m4a": "audio",
    ".wav": "audio",
    ".ogg": "audio",
    ".opus": "audio",
    ".flac": "audio",
}
# Kinds whose text comes from recognition and waits for the user's review.
RECOGNISED_KINDS = frozenset({"video", "audio"})

_BLANK_LINES = re.compile(r"\n\s*\n")
_MD_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_MD_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+")
_MD_EMPHASIS = re.compile(r"(\*\*|__|\*|`)")
_FRONT_MATTER = re.compile(r"\A---\n.*?\n---\n", re.DOTALL)

__all__ = ["ExtractionError", "Unit", "detect_kind", "extract_units"]


def detect_kind(filename: str) -> str:
    kind = KIND_BY_SUFFIX.get(Path(filename).suffix.lower())
    if kind is None:
        supported = ", ".join(sorted(KIND_BY_SUFFIX))
        raise ExtractionError(f"unsupported file type: {filename} (supported: {supported})")
    return kind


def decode_text(data: bytes) -> str:
    text = data.decode("utf-8-sig", errors="replace")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def pdf_pages(path: Path, pdftotext_bin: str) -> list[str]:
    try:
        proc = subprocess.run(
            [pdftotext_bin, "-enc", "UTF-8", "-eol", "unix", str(path), "-"],
            capture_output=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise ExtractionError(f"pdftotext not found ({pdftotext_bin}); install poppler") from exc
    if proc.returncode != 0:
        raise ExtractionError(f"pdftotext failed: {proc.stderr.decode(errors='replace').strip()}")
    pages = decode_text(proc.stdout).split("\f")
    # pdftotext ends the last page with a form feed.
    if pages and not pages[-1].strip():
        pages.pop()
    return pages


def _join_lines(block: str) -> str:
    lines = [ln.strip() for ln in block.split("\n") if ln.strip()]
    out = ""
    for line in lines:
        if out.endswith("-") and line[:1].islower():
            out = out[:-1] + line  # re-join a word hyphenated across lines
        elif out:
            out += " " + line
        else:
            out = line
    return re.sub(r"[ \t]+", " ", out)


def paragraphs(page_text: str) -> list[str]:
    blocks = [_join_lines(b) for b in _BLANK_LINES.split(page_text)]
    return [b for b in blocks if b]


def markdown_to_text(text: str) -> str:
    text = _FRONT_MATTER.sub("", text)
    out_lines = []
    for line in text.split("\n"):
        line = _MD_HEADING.sub("", line)
        line = _MD_IMAGE.sub(r"\1", line)
        line = _MD_LINK.sub(r"\1", line)
        line = _MD_EMPHASIS.sub("", line)
        out_lines.append(line)
    return "\n".join(out_lines)


def extract_units(path: Path, kind: str, settings: Settings) -> list[Unit]:
    """Return the material's pages, slides, or passages, each a list of paragraph blocks."""
    if kind == "pdf":
        return [Unit(f"p{n}", paragraphs(p)) for n, p in enumerate(pdf_pages(path, settings.ingest.pdftotext_bin), 1)]
    if kind == "pptx":
        return pptx_units(path, settings.ingest.slide_notes)
    if kind == "docx":
        return docx_units(path)
    if kind == "html":
        return html_units(decode_html(path.read_bytes()))
    if kind in RECOGNISED_KINDS:
        raise ExtractionError(f"{kind} needs speech recognition (groundcast.ingest.recognise_material)")
    text = decode_text(path.read_bytes())
    if kind == "markdown":
        text = markdown_to_text(text)
    return [Unit("p1", paragraphs(text))]
