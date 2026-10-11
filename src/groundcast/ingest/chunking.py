"""Chunking rules (spec section 5).

A chunk is one paragraph or text block, split further when longer than the
word limit, and never spans a page, slide, or transcript passage. Short
heading-like blocks are folded into the paragraph that follows them on the
same page, so a heading never becomes a chunk of its own.
"""

from __future__ import annotations

import re

from groundcast.ingest.units import Unit
from groundcast.models import Chunk

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[\"'(\[A-Z0-9])")
_HEADING_MAX_WORDS = 12


def chunk_id(material_id: str, locator: str, index: int) -> str:
    return f"{material_id}:{locator}:{index}"


def _is_heading(block: str) -> bool:
    return len(block.split()) <= _HEADING_MAX_WORDS and not block.rstrip().endswith((".", "!", "?", ":", ";", ","))


def _fold_headings(blocks: list[str]) -> list[str]:
    out: list[str] = []
    pending = ""
    for block in blocks:
        if _is_heading(block):
            pending = f"{pending}. {block}" if pending else block
            continue
        out.append(f"{pending}. {block}" if pending else block)
        pending = ""
    if pending:
        out.append(pending)
    return out


def split_long(text: str, max_words: int) -> list[str]:
    """Split text at sentence boundaries into pieces of at most max_words."""
    if len(text.split()) <= max_words:
        return [text]
    pieces: list[str] = []
    current: list[str] = []
    for sentence in _SENTENCE_END.split(text):
        words = sentence.split()
        if len(words) > max_words:
            if current:
                pieces.append(" ".join(current))
                current = []
            for start in range(0, len(words), max_words):
                pieces.append(" ".join(words[start : start + max_words]))
            continue
        if current and len(current) + len(words) > max_words:
            pieces.append(" ".join(current))
            current = []
        current.extend(words)
    if current:
        pieces.append(" ".join(current))
    return pieces


def chunk_units(material_id: str, units: list[Unit], max_words: int) -> list[Chunk]:
    chunks: list[Chunk] = []
    for unit in units:
        index = 0
        for block in _fold_headings(unit.blocks):
            for piece in split_long(block, max_words):
                index += 1
                chunks.append(
                    Chunk(
                        id=chunk_id(material_id, unit.locator, index),
                        material_id=material_id,
                        locator=unit.locator,
                        index=index,
                        text=piece,
                        confidence=unit.confidence,
                    )
                )
    return chunks


def chunk_pages(material_id: str, pages: list[list[str]], max_words: int) -> list[Chunk]:
    """Chunks of numbered pages (locators p1, p2, ...)."""
    units = [Unit(f"p{n}", blocks) for n, blocks in enumerate(pages, start=1)]
    return chunk_units(material_id, units, max_words)
