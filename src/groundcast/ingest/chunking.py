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


Folded = tuple[str, float | None, list[str]]


def _fold_headings(
    blocks: list[str], confidence: list[float] | None = None, uncertain: list[list[str]] | None = None
) -> list[Folded]:
    """Blocks with headings folded in; a folded block keeps the lower confidence of its parts."""
    confs: list[float | None] = list(confidence) if confidence else [None] * len(blocks)
    words = uncertain or [[] for _ in blocks]
    out: list[Folded] = []
    pending, pending_conf, pending_words = "", None, []

    def lower(a: float | None, b: float | None) -> float | None:
        return b if a is None else a if b is None else min(a, b)

    for block, conf, low in zip(blocks, confs, words):
        if _is_heading(block):
            pending = f"{pending}. {block}" if pending else block
            pending_conf, pending_words = lower(pending_conf, conf), pending_words + low
            continue
        out.append((f"{pending}. {block}" if pending else block, lower(pending_conf, conf), pending_words + low))
        pending, pending_conf, pending_words = "", None, []
    if pending:
        out.append((pending, pending_conf, pending_words))
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
        for block, block_conf, low in _fold_headings(unit.blocks, unit.block_confidence, unit.block_uncertain):
            for piece in split_long(block, max_words):
                index += 1
                chunks.append(
                    Chunk(
                        id=chunk_id(material_id, unit.locator, index),
                        material_id=material_id,
                        locator=unit.locator,
                        index=index,
                        text=piece,
                        confidence=block_conf if unit.block_confidence else unit.confidence,
                        uncertain=[w for w in dict.fromkeys(low) if w in piece.split()],
                    )
                )
    return chunks


def chunk_pages(material_id: str, pages: list[list[str]], max_words: int) -> list[Chunk]:
    """Chunks of numbered pages (locators p1, p2, ...)."""
    units = [Unit(f"p{n}", blocks) for n, blocks in enumerate(pages, start=1)]
    return chunk_units(material_id, units, max_words)
