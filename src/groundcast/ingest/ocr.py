"""Text recognition (OCR) for scans, photos, and handwriting.

Tesseract runs as a separate program on each image, or on each PDF page
that has no usable text layer (rendered by poppler's pdftoppm). Its word
boxes are grouped into paragraphs, each with the mean confidence of its
words. Recognised text is often wrong, handwriting especially, and the
Verifier would treat it as the truth, so it waits for the user's review
before any session may use it.
"""

from __future__ import annotations

import csv
import io
import subprocess
import tempfile
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from groundcast.config import OCRSettings
from groundcast.ingest.units import ExtractionError, Unit

Progress = Callable[[str], None]


@dataclass
class Paragraph:
    text: str
    confidence: float  # mean word confidence, 0 to 1
    uncertain: list[str] = field(default_factory=list)  # words below the review threshold


def _run(cmd: list[str], what: str, timeout_s: float) -> subprocess.CompletedProcess[bytes]:
    try:
        proc = subprocess.run(cmd, capture_output=True, check=False, timeout=timeout_s)
    except FileNotFoundError as exc:
        raise ExtractionError(f"{cmd[0]} not found; {what} needs it") from exc
    except subprocess.TimeoutExpired as exc:
        raise ExtractionError(f"{what} took longer than {timeout_s:.0f} s") from exc
    if proc.returncode != 0:
        raise ExtractionError(f"{what} failed: {proc.stderr.decode(errors='replace').strip()[:500]}")
    return proc


_SENTENCE_END = (".", "!", "?", ":", ";")


def paragraphs_from_tsv(tsv: str, review_below: float = 0.0) -> dict[int, list[Paragraph]]:
    """Tesseract's TSV output -> paragraphs per page (page numbers from 1).

    Tesseract sometimes breaks a paragraph in mid-sentence; a paragraph that
    does not end a sentence joins the next one when that starts in lower case
    or with a digit.
    """
    words: dict[tuple[int, int, int], list[tuple[int, str, float]]] = defaultdict(list)
    for row in csv.DictReader(io.StringIO(tsv), delimiter="\t", quoting=csv.QUOTE_NONE):
        text = (row.get("text") or "").strip()
        if row.get("level") != "5" or not text:
            continue
        conf = float(row["conf"])
        key = (int(row["page_num"]), int(row["block_num"]), int(row["par_num"]))
        words[key].append((int(row["line_num"]), text, max(conf, 0.0) / 100))
    pages: dict[int, list[Paragraph]] = defaultdict(list)
    for (page, _, _), items in sorted(words.items()):
        out, previous_line = "", None
        for line, text, _ in items:
            if previous_line is not None and line != previous_line and out.endswith("-") and text[:1].islower():
                out = out[:-1] + text  # a word hyphenated across lines
            else:
                out = f"{out} {text}" if out else text
            previous_line = line
        confidence = sum(c for _, _, c in items) / len(items)
        low = [text for _, text, c in items if c < review_below]
        paras = pages[page]
        if paras and not paras[-1].text.endswith(_SENTENCE_END) and (out[:1].islower() or out[:1].isdigit()):
            prev = paras[-1]
            n_prev, n_new = len(prev.text.split()), len(out.split())
            merged = (prev.confidence * n_prev + confidence * n_new) / (n_prev + n_new)
            hyphen = prev.text.endswith("-") and out[:1].islower()  # a word broken across the split
            text = prev.text[:-1] + out if hyphen else f"{prev.text} {out}"
            paras[-1] = Paragraph(text, round(merged, 3), prev.uncertain + low)
        else:
            paras.append(Paragraph(out, round(confidence, 3), low))
    return pages


class OCREngine(Protocol):
    def image(self, path: Path) -> dict[int, list[Paragraph]]:
        """Paragraphs per page of an image file (a TIFF may have several pages)."""
        ...

    def pdf_page(self, pdf: Path, page: int) -> list[Paragraph]:
        """Paragraphs of one PDF page, rendered as an image."""
        ...


class TesseractOCR:
    def __init__(self, cfg: OCRSettings) -> None:
        self.cfg = cfg

    def image(self, path: Path) -> dict[int, list[Paragraph]]:
        cmd = [self.cfg.tesseract_bin, str(path), "-", "-l", self.cfg.language, "--psm", str(self.cfg.psm)]
        if self.cfg.tessdata_dir:
            cmd += ["--tessdata-dir", self.cfg.tessdata_dir]
        # The option itself, not the "tsv" config file, which some packages lack.
        proc = _run(cmd + ["-c", "tessedit_create_tsv=1"], "text recognition (tesseract)", self.cfg.timeout_s)
        return paragraphs_from_tsv(proc.stdout.decode("utf-8", errors="replace"), self.cfg.review_below)

    def pdf_page(self, pdf: Path, page: int) -> list[Paragraph]:
        with tempfile.TemporaryDirectory(prefix="groundcast-ocr-") as tmp:
            prefix = Path(tmp) / "page"
            _run([self.cfg.pdftoppm_bin, "-r", str(self.cfg.dpi), "-f", str(page), "-l", str(page), "-singlefile",
                  "-png", str(pdf), str(prefix)], "rendering a PDF page (pdftoppm)", self.cfg.timeout_s)  # fmt: skip
            return self.image(prefix.with_suffix(".png")).get(1, [])


def pages_with_images(pdf: Path, cfg: OCRSettings) -> set[int]:
    """PDF pages holding an image of at least cfg.min_image_pixels pixels (a scan, not a logo)."""
    proc = _run([cfg.pdfimages_bin, "-list", str(pdf)], "listing PDF images (pdfimages)", cfg.timeout_s)
    pages = set()
    for line in proc.stdout.decode("utf-8", errors="replace").splitlines()[2:]:
        cols = line.split()
        if len(cols) > 4 and cols[0].isdigit() and cols[3].isdigit() and cols[4].isdigit():
            if int(cols[3]) * int(cols[4]) >= cfg.min_image_pixels:
                pages.add(int(cols[0]))
    return pages


def scanned_pages(pdf: Path, units: list[Unit], cfg: OCRSettings) -> list[int]:
    """Pages with almost no text layer but a page-sized image: these need recognition."""
    thin = [n for n, u in enumerate(units, start=1) if len(" ".join(u.blocks)) < cfg.min_page_chars]
    if not thin:
        return []
    with_images = pages_with_images(pdf, cfg)
    return [n for n in thin if n in with_images]


def _unit(page: int, paras: list[Paragraph]) -> Unit:
    return Unit(f"p{page}", [p.text for p in paras], block_confidence=[p.confidence for p in paras],
                block_uncertain=[p.uncertain for p in paras])  # fmt: skip


def units_from(pages: dict[int, list[Paragraph]]) -> list[Unit]:
    return [_unit(n, paras) for n, paras in sorted(pages.items())]


def make_ocr(cfg: OCRSettings) -> OCREngine:
    if cfg.engine == "none":
        raise ExtractionError("text recognition is switched off (ocr.engine = none)")
    return TesseractOCR(cfg)


def recognise_image(path: Path, ocr: OCREngine, progress: Progress) -> list[Unit]:
    progress(f"Recognising text in {path.name}")
    return units_from(ocr.image(path))


def recognise_pdf_pages(path: Path, pages: list[int], ocr: OCREngine, progress: Progress) -> dict[int, Unit]:
    """Recognise the given PDF pages; returns a unit per page number."""
    out = {}
    for n, page in enumerate(pages, start=1):
        progress(f"Recognising text on page {page} ({n} of {len(pages)})")
        out[page] = _unit(page, ocr.pdf_page(path, page))
    return out
