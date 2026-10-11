"""S0 Ingest: materials -> text chunks with stable IDs."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

from groundcast.config import Settings
from groundcast.ingest.chunking import chunk_pages
from groundcast.ingest.extract import ExtractionError, detect_kind, extract_pages
from groundcast.models import Material
from groundcast.storage import Store

MATERIAL_ID_LENGTH = 8

__all__ = ["ExtractionError", "ingest_file"]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def ingest_file(path: Path, store: Store, settings: Settings, filename: str | None = None) -> Material:
    """Copy a file into the data directory, extract it, and store its chunks.

    Ingesting the same content twice returns the existing record.
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
    try:
        pages = extract_pages(target, kind, settings.ingest.pdftotext_bin)
        chunks = chunk_pages(material_id, pages, settings.ingest.chunk_max_words)
        if not chunks:
            raise ExtractionError(f"no text found in {filename}; scanned documents arrive in M5")
        material = Material(
            id=material_id,
            sha256=sha,
            filename=Path(filename).name,
            kind=kind,
            stored_name=stored_name,
            pages=len(pages),
            words=sum(len(c.text.split()) for c in chunks),
        )
        store.save_material(material, chunks)
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return material
