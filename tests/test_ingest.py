from pathlib import Path

import pytest

from groundcast.config import Settings
from groundcast.ingest import ExtractionError, ingest_file
from groundcast.ingest.chunking import chunk_pages, split_long
from groundcast.storage import Store

from .conftest import FIXTURES


def _minimal_pdf(pages: list[str]) -> bytes:
    """Build a small valid PDF with one line of Helvetica text per page."""
    objects: list[bytes] = []
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(len(pages)))
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode())
    font_no = 3 + 2 * len(pages)
    for i, text in enumerate(pages):
        content = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {4 + 2 * i} 0 R "
            f"/Resources << /Font << /F1 {font_no} 0 R >> >> >>".encode()
        )
        objects.append(b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    out = b"%PDF-1.4\n"
    offsets = []
    for n, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{n} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


def test_markdown_chunks_have_stable_ids(settings: Settings, store: Store) -> None:
    m = ingest_file(FIXTURES / "tides.md", store, settings)
    chunks = store.get_chunks(m.id)
    assert m.kind == "markdown" and m.pages == 1 and len(m.id) == 8
    assert [c.id for c in chunks] == [f"{m.id}:p1:{i}" for i in range(1, len(chunks) + 1)]
    # Headings are folded into the next paragraph, never chunks of their own.
    texts = [c.text for c in chunks]
    assert not {"Tides", "What causes tides", "Spring and neap tides"} & set(texts)
    assert texts[0] == "Tides. Self-written test material for groundcast."
    assert any(c.text.startswith("What causes tides. Tides are") for c in chunks)
    assert "#" not in " ".join(c.text for c in chunks)


def test_ingest_is_idempotent(settings: Settings, store: Store) -> None:
    a = ingest_file(FIXTURES / "tides.md", store, settings)
    b = ingest_file(FIXTURES / "tides.md", store, settings)
    assert a == b
    assert len(store.list_materials()) == 1


def test_pdf_keeps_pages(settings: Settings, store: Store, tmp_path: Path) -> None:
    pdf = tmp_path / "two.pdf"
    pdf.write_bytes(_minimal_pdf(["The first page talks about the Moon.", "The second page talks about the Sun."]))
    m = ingest_file(pdf, store, settings)
    chunks = store.get_chunks(m.id)
    assert m.pages == 2
    assert [c.locator for c in chunks] == ["p1", "p2"]
    assert "Sun" in chunks[1].text


def test_unsupported_type(settings: Settings, store: Store, tmp_path: Path) -> None:
    f = tmp_path / "notes.docx"
    f.write_bytes(b"x")
    with pytest.raises(ExtractionError):
        ingest_file(f, store, settings)


def test_split_long_respects_limit() -> None:
    text = " ".join(f"Sentence number {i} has five words." for i in range(40))
    pieces = split_long(text, 30)
    assert all(len(p.split()) <= 30 for p in pieces)
    assert " ".join(pieces).split() == text.split()


def test_chunks_never_cross_pages() -> None:
    chunks = chunk_pages("abcd1234", [["One paragraph on page one."], ["Another paragraph on page two."]], 100)
    assert [c.id for c in chunks] == ["abcd1234:p1:1", "abcd1234:p2:1"]
