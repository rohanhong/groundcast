"""M3 material formats: PowerPoint, Word, web pages, video and audio."""

from __future__ import annotations

import http.server
import os
import threading
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from groundcast.config import Settings
from groundcast.ingest import ExtractionError, ingest_file, ingest_url, interrupted_recognitions, review_material
from groundcast.ingest.asr import Spoken, passages
from groundcast.ingest.web import html_units, page_title, parse_html
from groundcast.material_view import chunk_label, material_path
from groundcast.models import Brief
from groundcast.sessions import new_session
from groundcast.storage import Store
from groundcast.web.app import create_app

from .builders import w_par, write_docx, write_pptx


def test_pptx_gives_one_unit_per_visible_slide(settings: Settings, store: Store, tmp_path: Path) -> None:
    deck = write_pptx(
        tmp_path / "tides.pptx",
        [
            [("title", ["Tides"]), (None, ["Two high tides a day", "Caused by the Moon"])],
            [("title", ["Backup"]), (None, ["Hidden detail"])],
            [("title", ["Spring tides"]), (None, ["Sun and Moon in line."])],
        ],
        notes={3: "Spring tides happen near new and full moon."},
        hidden=frozenset({2}),
    )
    m = ingest_file(deck, store, settings)
    chunks = store.get_chunks(m.id)
    assert m.kind == "pptx" and m.pages == 2
    assert [c.locator for c in chunks] == ["s1", "s3", "s3"]
    assert chunks[0].text == "Tides. Two high tides a day. Caused by the Moon."  # title folded, bullets joined
    assert chunks[2].text == "Speaker notes: Spring tides happen near new and full moon."
    assert "Hidden" not in " ".join(c.text for c in chunks)
    assert not any(c.text in ("1.", "3.") for c in chunks)  # slide numbers skipped
    assert chunk_label(chunks[1], m) == "tides.pptx, slide 3, passage 1"
    assert material_path(chunks[1], m) == f"materials/{m.id}.view.html#s3-1"
    view = (store.materials_dir / f"{m.id}.view.html").read_text(encoding="utf-8")
    assert 'id="s3-1"' in view and "Slide 3" in view
    assert '<html lang="en" translate="no">' in view  # the text the sources point at is never machine-translated


def test_pptx_notes_can_be_left_out(settings: Settings, store: Store, tmp_path: Path) -> None:
    settings.ingest.slide_notes = False
    deck = write_pptx(tmp_path / "a.pptx", [[(None, ["Slide text."])]], notes={1: "Secret notes."})
    m = ingest_file(deck, store, settings)
    assert [c.text for c in store.get_chunks(m.id)] == ["Slide text."]


def test_docx_pages_follow_word_page_breaks(settings: Settings, store: Store, tmp_path: Path) -> None:
    table = (
        "<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Month</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Range</w:t></w:r></w:p>"
        "</w:tc></w:tr><w:tr><w:tc><w:p><w:r><w:t>March</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>4 m</w:t>"
        "</w:r></w:p></w:tc></w:tr></w:tbl>"
    )
    doc = write_docx(
        tmp_path / "notes.docx",
        w_par("The Moon pulls the oceans.") + w_par("Spring tides are larger.", page_break_before=True)
        + table + w_par("Neap tides are smaller.", rendered_break=True),
    )
    m = ingest_file(doc, store, settings)
    chunks = store.get_chunks(m.id)
    assert m.kind == "docx" and m.pages == 3
    assert [(c.locator, c.text) for c in chunks] == [
        ("p1", "The Moon pulls the oceans."),
        ("p2", "Spring tides are larger."),
        ("p2", "Month: March; Range: 4 m."),  # each row names its column headers
        ("p3", "Neap tides are smaller."),
    ]
    assert chunk_label(chunks[1], m) == "notes.docx, page 2, passage 1"


def test_docx_without_breaks_is_one_page(settings: Settings, store: Store, tmp_path: Path) -> None:
    m = ingest_file(write_docx(tmp_path / "a.docx", w_par("One fact.") + w_par("Another fact.")), store, settings)
    chunk = store.get_chunks(m.id)[0]
    assert m.pages == 1 and chunk_label(chunk, m) == "a.docx, passage 1"


def test_damaged_office_file_is_refused(settings: Settings, store: Store, tmp_path: Path) -> None:
    bad = tmp_path / "bad.docx"
    bad.write_bytes(b"not a zip")
    with pytest.raises(ExtractionError):
        ingest_file(bad, store, settings)
    assert store.list_materials() == []


PAGE = """<!doctype html><html><head><title>Tides | Example Site</title>
<meta property="og:title" content="How tides work"><script>var x = "<p>not text</p>";</script></head>
<body><nav><ul><li>Home</li><li>About</li></ul></nav>
<div class="sidebar"><p>Subscribe to our newsletter for weekly updates on everything.</p></div>
<article><h1>How tides work</h1>
<p>The Moon's gravity pulls the oceans into two bulges, one on each side of the Earth.</p>
<div class="share-buttons">Share this</div>
<div class="article-content"><p>Most coasts see two high tides a day.</p>
<ul><li>Spring tides</li><li>Neap tides</li></ul>
<table><tr><th>Tide</th><th>Range</th></tr><tr><td>Spring</td><td>Large</td></tr></table></div>
<footer>Copyright notice</footer></article>
<div class="comments"><p>Great article, thanks for writing it up so clearly!</p></div>
</body></html>"""


def test_web_page_keeps_the_article_and_drops_the_furniture() -> None:
    blocks = html_units(PAGE)[0].blocks
    text = " ".join(blocks)
    assert blocks[0] == "How tides work"
    assert "two bulges" in text and "two high tides a day" in text
    assert "Spring tides" in blocks and "Tide: Spring; Range: Large." in blocks
    for furniture in ("Home", "Subscribe", "Share this", "Copyright", "Great article", "not text"):
        assert furniture not in text
    assert page_title(parse_html(PAGE)) == "How tides work"


def test_page_without_article_uses_the_densest_block() -> None:
    page = ("<html><body><div id='menu'><p>Menu item one, menu item two, menu item three.</p></div>"
            "<div><div><p>The lake froze early in the cold winter of that year.</p>"
            "<p>Ice covered it for one hundred and two days, a record for the station.</p></div></div>"
            "<div class='footer'><p>Contact us at the office during working hours please.</p></div></body></html>")
    text = " ".join(html_units(page)[0].blocks)
    assert "one hundred and two days" in text and "Menu" not in text and "Contact" not in text


@pytest.fixture
def web_server(tmp_path: Path) -> Iterator[Callable[[str], str]]:
    """Serve tmp_path over HTTP on a free local port; returns a URL builder."""
    root = tmp_path / "site"
    root.mkdir()
    (root / "tides.html").write_text(PAGE, encoding="utf-8")
    (root / "data.bin").write_bytes(b"\x00\x01")
    handler = lambda *a, **k: http.server.SimpleHTTPRequestHandler(*a, directory=str(root), **k)  # noqa: E731
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield lambda name: f"http://127.0.0.1:{server.server_address[1]}/{name}"
    server.shutdown()


def test_ingest_url_records_address_and_date(settings: Settings, store: Store, web_server) -> None:  # type: ignore[no-untyped-def]
    m = ingest_url(web_server("tides.html"), store, settings)
    assert m.kind == "html" and m.filename == "How tides work.html"
    assert m.source_url == web_server("tides.html") and m.fetched_at is not None
    assert any("two bulges" in c.text for c in store.get_chunks(m.id))
    view = (store.materials_dir / f"{m.id}.view.html").read_text(encoding="utf-8")
    assert m.source_url in view
    with pytest.raises(ExtractionError, match="application/octet-stream"):
        ingest_url(web_server("data.bin"), store, settings)
    with pytest.raises(ExtractionError, match="404"):
        ingest_url(web_server("missing.html"), store, settings)
    with pytest.raises(ExtractionError, match="http"):
        ingest_url("file:///etc/passwd", store, settings)


class FakeTranscriber:
    def __init__(self, spoken: list[Spoken] | None = None, error: Exception | None = None) -> None:
        self.spoken = spoken or [
            Spoken(0.0, 4.0, "Tides rise and fall twice a day.", 0.95),
            Spoken(4.2, 9.0, "The Moon's pull causes them.", 0.5),
            Spoken(12.5, 16.0, "Spring tides come at full moon.", 0.9),
        ]
        self.error = error
        self.calls = 0

    def transcribe(self, path: Path, progress: Callable[[str], None]) -> tuple[list[Spoken], float]:
        self.calls += 1
        if self.error:
            raise self.error
        return self.spoken, 20.0


def _video(tmp_path: Path) -> Path:
    path = tmp_path / "lecture.mp4"
    path.write_bytes(b"fake video bytes")
    return path


def test_passages_split_at_pauses_and_length() -> None:
    spoken = [Spoken(0, 2, "a b c", 1.0), Spoken(2.5, 4, "d e", 0.5), Spoken(7, 8, "f", 1.0),
              Spoken(8.1, 9, "g h i j k", 1.0)]  # fmt: skip
    units = passages(spoken, max_words=5, gap_s=2.0, max_s=60)
    assert [(u.locator, u.blocks, u.confidence) for u in units] == [
        ("t0", ["a b c d e"], 0.8),  # weighed by words: (3 * 1.0 + 2 * 0.5) / 5
        ("t7", ["f"], 1.0),  # the pause before it is 3 s
        ("t8", ["g h i j k"], 1.0),  # f plus these would pass 5 words
    ]


def test_video_waits_for_review_before_sessions(settings: Settings, store: Store, tmp_path: Path) -> None:
    m = ingest_file(_video(tmp_path), store, settings, transcriber=FakeTranscriber())
    chunks = store.get_chunks(m.id)
    assert (m.kind, m.status, m.duration_s, m.pages) == ("video", "review", 20.0, 2)
    assert [c.id for c in chunks] == [f"{m.id}:t0:1", f"{m.id}:t12:1"]
    assert chunks[0].confidence is not None and chunks[0].confidence < settings.asr.review_below
    assert chunk_label(chunks[1], m) == "lecture.mp4, at 0:12"
    assert material_path(chunks[1], m) == f"materials/{m.stored_name}#t=12"
    with pytest.raises(ValueError, match="review"):
        new_session(store, Brief(focus="tides", material_ids=[m.id]))

    m = review_material(store, m.id, {chunks[0].id: "Tides rise and fall twice a day. The Moon's pull causes them!",
                                      chunks[1].id: "  "})  # fmt: skip
    kept = store.get_chunks(m.id)
    assert m.status == "ready" and m.reviewed_at is not None
    assert [(c.id, c.edited) for c in kept] == [(chunks[0].id, True)]  # same ID, corrected text; the other dropped
    assert new_session(store, Brief(focus="tides", material_ids=[m.id])).brief.material_ids == [m.id]
    with pytest.raises(ValueError, match="unknown"):
        review_material(store, m.id, {"nope:t0:1": "x"})


def test_failed_recognition_is_recorded(settings: Settings, store: Store, tmp_path: Path) -> None:
    with pytest.raises(ExtractionError):
        ingest_file(_video(tmp_path), store, settings, transcriber=FakeTranscriber(error=ExtractionError("no GPU")))
    [m] = store.list_materials()
    assert (m.status, m.error) == ("failed", "no GPU")


def test_interrupted_recognition_can_resume(settings: Settings, store: Store, tmp_path: Path) -> None:
    m = ingest_file(_video(tmp_path), store, settings, defer=True)
    assert m.status == "processing" and store.get_chunks(m.id) == []
    m.pid = os.getppid()  # another live process is working on it
    store.save_material(m, [])
    assert interrupted_recognitions(store) == []
    m.pid = 999_999_999  # stopped
    store.save_material(m, [])
    assert [x.id for x in interrupted_recognitions(store)] == [m.id]


class ImmediateRunner:
    def submit(self, record: object) -> None:
        pass

    def submit_task(self, task: Callable[[], object]) -> None:
        task()


def test_web_upload_recognises_then_review_confirms(settings: Settings, tmp_path: Path, web_server) -> None:  # type: ignore[no-untyped-def]
    transcriber = FakeTranscriber(error=ExtractionError("model missing"))
    app = create_app(settings, runner=ImmediateRunner(), transcriber=transcriber)  # type: ignore[arg-type]
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        files = {"files": ("lecture.mp4", b"fake video", "video/mp4")}
        [m] = client.post("/api/materials", files=files).json()
        assert m["status"] == "processing"  # returned before recognition ran
        m = client.get("/api/materials").json()[0]
        assert (m["status"], m["error"]) == ("failed", "model missing")
        transcriber.error = None
        assert client.post(f"/api/materials/{m['id']}/retry").json()["status"] == "processing"
        assert client.get("/api/materials").json()[0]["status"] == "review"
        brief = {"focus": "tides", "material_ids": [m["id"]]}
        assert client.post("/api/sessions", json=brief).status_code == 422
        chunks = client.get(f"/api/materials/{m['id']}/chunks").json()
        r = client.post(f"/api/materials/{m['id']}/review", json={"corrections": {chunks[1]["id"]: "Fixed text."}})
        assert r.status_code == 200 and r.json()["status"] == "ready"
        assert client.get(f"/api/materials/{m['id']}/chunks").json()[1]["text"] == "Fixed text."
        assert client.post(f"/api/materials/{m['id']}/retry").status_code == 409

        page = client.post("/api/materials/url", json={"url": web_server("tides.html")}).json()
        assert page["kind"] == "html"
        raw = client.get(f"/data/materials/{page['stored_name']}")
        assert raw.headers["content-security-policy"] == "sandbox"  # someone else's HTML runs no scripts here
        assert client.post("/api/materials/url", json={"url": "ftp://x"}).status_code == 422
