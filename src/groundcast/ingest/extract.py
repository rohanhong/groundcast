"""Text extraction: file -> pages -> paragraph blocks.

PDF text comes from poppler's pdftotext, run as a separate program (GPL).
Markdown and plain text have no pages and count as one page.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

KIND_BY_SUFFIX = {
    ".pdf": "pdf",
    ".md": "markdown",
    ".markdown": "markdown",
    ".txt": "text",
}

_BLANK_LINES = re.compile(r"\n\s*\n")
_MD_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_MD_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+")
_MD_EMPHASIS = re.compile(r"(\*\*|__|\*|`)")
_FRONT_MATTER = re.compile(r"\A---\n.*?\n---\n", re.DOTALL)


class ExtractionError(RuntimeError):
    pass


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


def extract_pages(path: Path, kind: str, pdftotext_bin: str) -> list[list[str]]:
    """Return a list of pages, each a list of paragraph blocks."""
    if kind == "pdf":
        return [paragraphs(p) for p in pdf_pages(path, pdftotext_bin)]
    text = decode_text(path.read_bytes())
    if kind == "markdown":
        text = markdown_to_text(text)
    return [paragraphs(text)]
