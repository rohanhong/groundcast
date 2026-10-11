from groundcast.audio import Chapter, ffmetadata


def test_chapter_titles_are_escaped_for_ffmpeg() -> None:
    text = ffmetadata([Chapter("Ice; part=1 #2", 0.0, 1.5), Chapter("Back\\slash", 1.5, 3.25)])
    assert text.startswith(";FFMETADATA1\n")
    assert "title=Ice\\; part\\=1 \\#2\n" in text
    assert "title=Back\\\\slash\n" in text
    assert "START=1500\nEND=3250\n" in text
