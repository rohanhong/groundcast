"""S0 Ingest: materials -> text chunks with stable IDs.

Text formats are extracted at once. Video and audio go through speech
recognition, and images and PDF pages without a text layer through text
recognition (OCR). Both are slow: the file is stored first (status
processing), recognised by recognise_material, and then waits for the user
to check and correct the text (status review) before any session may use it
(spec S0).
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import tempfile
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from groundcast.config import Settings
from groundcast.ingest.asr import Transcriber, make_transcriber, passages
from groundcast.ingest.chunking import chunk_units
from groundcast.ingest.extract import MEDIA_KINDS, RECOGNISED_KINDS, detect_kind, extract_units
from groundcast.ingest.ocr import OCREngine, make_ocr, recognise_image, recognise_pdf_pages, scanned_pages
from groundcast.ingest.units import ExtractionError, Unit
from groundcast.ingest.web import decode_html, fetch, page_title, parse_html
from groundcast.models import Material, utc_now
from groundcast.storage import Store

MATERIAL_ID_LENGTH = 8
# Media types of fetched addresses, and the file suffix each is stored with.
FETCHED_SUFFIX = {"text/html": ".html", "application/xhtml+xml": ".html", "application/pdf": ".pdf",
                  "text/plain": ".txt", "text/markdown": ".md"}  # fmt: skip
_UNSAFE_NAME = re.compile(r"[^\w .,()'-]+")

__all__ = [
    "ExtractionError",
    "ingest_file",
    "ingest_url",
    "recognise_material",
    "review_material",
    "interrupted_recognitions",
]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def ingest_file(
    path: Path,
    store: Store,
    settings: Settings,
    filename: str | None = None,
    *,
    source_url: str = "",
    fetched_at: datetime | None = None,
    transcriber: Transcriber | None = None,
    ocr: OCREngine | None = None,
    defer: bool = False,
) -> Material:
    """Copy a file into the data directory, extract it, and store its chunks.

    Ingesting the same content twice returns the existing record. Material
    that needs recognition is recognised here too unless defer is set; the
    caller then runs recognise_material, for example in a background worker.
    """
    filename = filename or path.name
    kind = detect_kind(filename)
    sha = _sha256(path)
    material_id = sha[:MATERIAL_ID_LENGTH]
    if store.has_material(material_id):
        existing = store.get_material(material_id)
        if existing.sha256 != sha:
            raise ExtractionError(f"material ID collision on {material_id}; rename is not supported yet")
        return existing

    stored_name = f"{material_id}{Path(filename).suffix.lower()}"
    target = store.materials_dir / stored_name
    shutil.copyfile(path, target)
    material = Material(
        id=material_id,
        sha256=sha,
        filename=Path(filename).name,
        kind=kind,
        stored_name=stored_name,
        pages=0,
        words=0,
        source_url=source_url,
        fetched_at=fetched_at,
    )
    try:
        units = [] if kind in RECOGNISED_KINDS else extract_units(target, kind, settings)
        if kind == "pdf" and settings.ocr.engine != "none":
            material.ocr_pages = scanned_pages(target, units, settings.ocr)
        if kind in RECOGNISED_KINDS or material.ocr_pages:
            material.status = "processing"
            material.pid = os.getpid()
            store.save_material(material, [])
            if not defer:
                material = recognise_material(store, settings, material_id, transcriber, ocr)
            return material
        chunks = chunk_units(material_id, units, settings.ingest.chunk_max_words)
        if not chunks:
            raise ExtractionError(f"no text found in {filename}")
        material.pages = len(units)
        material.words = sum(len(c.text.split()) for c in chunks)
        store.save_material(material, chunks)
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return material


def _recognised_units(
    material: Material,
    store: Store,
    settings: Settings,
    transcriber: Transcriber | None,
    ocr: OCREngine | None,
    progress: Callable[[str], None],
) -> list[Unit]:
    path = store.material_path(material)
    if material.kind in MEDIA_KINDS:
        spoken, material.duration_s = (transcriber or make_transcriber(settings)).transcribe(path, progress)
        cfg = settings.asr
        return passages(spoken, settings.ingest.chunk_max_words, cfg.paragraph_gap_s, cfg.max_passage_s)
    engine = ocr or make_ocr(settings.ocr)
    if material.kind == "image":
        return recognise_image(path, engine, progress)
    # A PDF: the text layer where it has one, recognised text on the other pages.
    units = extract_units(path, material.kind, settings)
    recognised = recognise_pdf_pages(path, material.ocr_pages, engine, progress)
    return [recognised.get(n, unit) for n, unit in enumerate(units, start=1)]


def recognise_material(
    store: Store,
    settings: Settings,
    material_id: str,
    transcriber: Transcriber | None = None,
    ocr: OCREngine | None = None,
    progress: Callable[[str], None] | None = None,
) -> Material:
    """Recognise the speech or text of a stored material; it then waits for review."""
    material = store.get_material(material_id)
    material.status, material.pid, material.error = "processing", os.getpid(), ""
    store.save_material(material, [])
    try:
        units = _recognised_units(material, store, settings, transcriber, ocr, progress or (lambda _: None))
        chunks = chunk_units(material.id, units, settings.ingest.chunk_max_words)
        if not chunks:
            what = "speech" if material.kind in MEDIA_KINDS else "text"
            raise ExtractionError(f"no {what} found in {material.filename}")
    except Exception as exc:
        material.status, material.pid = "failed", None
        material.error = str(exc) if isinstance(exc, ExtractionError) else f"{type(exc).__name__}: {exc}"
        store.save_material(material, [])
        if isinstance(exc, ExtractionError):
            raise
        raise ExtractionError(material.error) from exc
    material.status, material.pid = "review", None
    material.pages = len(units)
    material.words = sum(len(c.text.split()) for c in chunks)
    review_below = settings.asr.review_below if material.kind in MEDIA_KINDS else settings.ocr.review_below
    store.save_material(material, chunks, review_below)
    return material


def review_material(store: Store, material_id: str, corrections: dict[str, str]) -> Material:
    """Apply the user's corrections (chunk ID -> text; empty text drops it) and confirm the text.

    Chunk IDs stay as they are, so sessions can cite corrected text by the same IDs.
    """
    material = store.get_material(material_id)
    if material.status not in ("review", "ready"):
        raise ValueError(f"{material.filename} is {material.status}; there is no text to review yet")
    chunks = store.get_chunks(material_id)
    unknown = set(corrections) - {c.id for c in chunks}
    if unknown:
        raise ValueError(f"unknown passages: {', '.join(sorted(unknown))}")
    kept = []
    for chunk in chunks:
        if chunk.id in corrections:
            text = " ".join(corrections[chunk.id].split())
            if not text:
                continue
            if text != chunk.text:
                chunk.text, chunk.edited, chunk.uncertain = text, True, []
        kept.append(chunk)
    if not kept:
        raise ValueError("every passage would be removed; delete the material instead")
    material.status, material.reviewed_at = "ready", utc_now()
    material.words = sum(len(c.text.split()) for c in kept)
    store.save_material(material, kept)
    return material


def interrupted_recognitions(store: Store) -> list[Material]:
    """Materials left in processing by a process that has stopped; recognition can start again."""
    from groundcast.sessions import pid_alive

    return [
        m
        for m in store.list_materials()
        if m.status == "processing" and not (m.pid is not None and m.pid != os.getpid() and pid_alive(m.pid))
    ]


def _fetched_name(title: str, url: str, suffix: str) -> str:
    name = _UNSAFE_NAME.sub(" ", title).strip() or _UNSAFE_NAME.sub(" ", url.split("://", 1)[-1]).strip()
    return f"{name[:80].strip()}{suffix}"


def ingest_url(url: str, store: Store, settings: Settings) -> Material:
    """Fetch a web page (or a PDF or text file by address) and ingest it, recording the address and date."""
    cfg = settings.ingest
    fetched = fetch(url.strip(), cfg.fetch_timeout_s, cfg.fetch_max_bytes, cfg.user_agent)
    suffix = FETCHED_SUFFIX.get(fetched.content_type)
    if suffix is None:
        raise ExtractionError(f"{url} is {fetched.content_type}; groundcast reads web pages, PDF, and text")
    title = ""
    if suffix == ".html":
        title = page_title(parse_html(decode_html(fetched.data, fetched.charset)))
    with tempfile.TemporaryDirectory(prefix="groundcast-fetch-") as tmp:
        path = Path(tmp) / f"page{suffix}"
        path.write_bytes(fetched.data)
        return ingest_file(path, store, settings, _fetched_name(title, fetched.url, suffix),
                           source_url=fetched.url, fetched_at=fetched.fetched_at)  # fmt: skip
