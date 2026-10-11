"""What every extractor returns: the text of a material, page by page."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_SPACES = re.compile(r"\s+")
_END_PUNCTUATION = (".", "!", "?", ":", ";")


class ExtractionError(RuntimeError):
    pass


@dataclass
class Unit:
    """One page, slide, or transcript passage: the span a chunk never crosses."""

    locator: str  # p<page>, s<slide>, or t<start second>
    blocks: list[str] = field(default_factory=list)  # paragraphs or text boxes, in reading order
    confidence: float | None = None  # recognised text only
    # Recognised text only: a confidence per block, when blocks differ (OCR
    # paragraphs), and the low-confidence words of each block.
    block_confidence: list[float] | None = None
    block_uncertain: list[list[str]] | None = None


def table_text(rows: list[list[str]]) -> str:
    """A table as one block of sentences; each row names its column headers.

    "Station: Deep; Depth: 31 m." stays meaningful in a chunk of its own,
    where a bare "Deep; 31 m." would not.
    """
    rows = [[_SPACES.sub(" ", c).strip() for c in row] for row in rows]
    rows = [row for row in rows if any(row)]
    header = rows[0] if len(rows) > 1 and all(rows[0]) else None
    out = []
    for row in rows[1:] if header else rows:
        if header and len(row) == len(header):
            text = "; ".join(f"{h}: {c}" for h, c in zip(header, row) if c)
        else:
            text = "; ".join(c for c in row if c)
        out.append(text if text.endswith(_END_PUNCTUATION) else text + ".")
    return " ".join(out)
