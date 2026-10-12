"""Text recognition for images and scanned PDF pages."""

from pathlib import Path

import pytest

from groundcast.config import Settings
from groundcast.ingest import ExtractionError, ingest_file, review_material
from groundcast.ingest import ocr as ocr_module
from groundcast.ingest.ocr import Paragraph, paragraphs_from_tsv
from groundcast.material_view import chunk_label, material_path
from groundcast.models import Brief
from groundcast.sessions import new_session
from groundcast.storage import Store

from .test_ingest import _minimal_pdf

HEADER = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext"


def _word(page: int, block: int, par: int, line: int, conf: float, text: str) -> str:
    return f"5\t{page}\t{block}\t{par}\t{line}\t1\t0\t0\t1\t1\t{conf}\t{text}"


def test_tsv_paragraphs_rejoin_split_sentences_and_flag_words() -> None:
    tsv = "\n".join([
        HEADER,
        "1\t1\t0\t0\t0\t0\t0\t0\t1\t1\t-1\t",  # page row, no text
        _word(1, 1, 1, 1, 95, "Field"), _word(1, 1, 1, 1, 95, "notes"),
        _word(1, 2, 1, 1, 90, "The"), _word(1, 2, 1, 1, 40, "Woon"), _word(1, 2, 1, 1, 90, "pulls"),
        _word(1, 2, 1, 2, 90, "the"), _word(1, 2, 1, 2, 90, "oce-"),
        _word(1, 3, 1, 1, 90, "ans"), _word(1, 3, 1, 1, 90, "daily."),  # Tesseract split the sentence
        _word(2, 1, 1, 1, 80, "Second"), _word(2, 1, 1, 1, 80, "page."),
    ])  # fmt: skip
    pages = paragraphs_from_tsv(tsv, review_below=0.8)
    texts = [p.text for p in pages[1]]
    assert texts[0] == "Field notes"  # ends no sentence, but the next starts upper case: a heading
    assert texts[1] == "The Woon pulls the oceans daily."
    assert pages[1][1].uncertain == ["Woon"] and pages[2][0].text == "Second page."


class FakeOCR:
    def __init__(self) -> None:
        self.pdf_pages: list[int] = []

    def image(self, path: Path) -> dict[int, list[Paragraph]]:
        return {1: [Paragraph("Tides - my notes", 0.9), Paragraph("The Woon pulls the oceans.", 0.6, ["Woon"])]}

    def pdf_page(self, pdf: Path, page: int) -> list[Paragraph]:
        self.pdf_pages.append(page)
        return [Paragraph("Scanned page about neap tides.", 0.95)]


def test_image_waits_for_review(settings: Settings, store: Store, tmp_path: Path) -> None:
    image = tmp_path / "notes.png"
    image.write_bytes(b"fake png")
    m = ingest_file(image, store, settings, ocr=FakeOCR())
    [chunk] = store.get_chunks(m.id)
    assert (m.kind, m.status, m.pages) == ("image", "review", 1)
    assert chunk.text == "Tides - my notes. The Woon pulls the oceans." and chunk.uncertain == ["Woon"]
    assert chunk.confidence == 0.6  # the heading folded in keeps the lower confidence
    assert material_path(chunk, m) == f"materials/{m.stored_name}" and chunk_label(chunk, m) == "notes.png, passage 1"
    with pytest.raises(ValueError, match="review"):
        new_session(store, Brief(focus="tides", material_ids=[m.id]))
    m = review_material(store, m.id, {chunk.id: "Tides - my notes. The Moon pulls the oceans."})
    assert m.status == "ready" and store.get_chunks(m.id)[0].uncertain == []
    view = (store.materials_dir / f"{m.id}.view.html").read_text(encoding="utf-8")
    assert "recognised text, checked by you" in view


def test_only_scanned_pdf_pages_are_recognised(settings: Settings, store: Store, tmp_path: Path,
                                               monkeypatch: pytest.MonkeyPatch) -> None:  # fmt: skip
    pdf = tmp_path / "mixed.pdf"
    pdf.write_bytes(_minimal_pdf(["The first page has a text layer about tides.", "", ""]))
    # Page 2 holds a page-sized image (a scan); page 3 is simply blank.
    monkeypatch.setattr(ocr_module, "pages_with_images", lambda path, cfg: {2})
    engine = FakeOCR()
    m = ingest_file(pdf, store, settings, ocr=engine)
    chunks = store.get_chunks(m.id)
    assert (m.status, m.ocr_pages, engine.pdf_pages, m.pages) == ("review", [2], [2], 3)
    assert [(c.locator, c.confidence) for c in chunks] == [("p1", None), ("p2", 0.95)]
    assert "page(s) 2" in (store.materials_dir / f"{m.id}.view.html").read_text(encoding="utf-8")


def test_text_pdf_needs_no_review(settings: Settings, store: Store, tmp_path: Path,
                                  monkeypatch: pytest.MonkeyPatch) -> None:  # fmt: skip
    monkeypatch.setattr(ocr_module, "pages_with_images", lambda path, cfg: {1})
    pdf = tmp_path / "text.pdf"
    pdf.write_bytes(_minimal_pdf(["A page with plenty of text about the Moon and tides."]))
    assert ingest_file(pdf, store, settings).status == "ready"


def test_ocr_switched_off_leaves_a_scan_without_text(settings: Settings, store: Store, tmp_path: Path) -> None:
    settings.ocr.engine = "none"
    pdf = tmp_path / "scan.pdf"
    pdf.write_bytes(_minimal_pdf([""]))
    with pytest.raises(ExtractionError, match="no text"):
        ingest_file(pdf, store, settings)
    image = tmp_path / "photo.jpg"
    image.write_bytes(b"x")
    with pytest.raises(ExtractionError, match="switched off"):
        ingest_file(image, store, settings)
