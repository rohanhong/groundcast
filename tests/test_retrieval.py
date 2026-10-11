from groundcast.models import Chunk
from groundcast.retrieval import BM25Index


def _chunk(i: int, text: str) -> Chunk:
    return Chunk(id=f"m:p1:{i}", material_id="m", locator="p1", index=i, text=text)


def test_bm25_ranks_relevant_chunk_first() -> None:
    index = BM25Index(
        [
            _chunk(1, "The Moon pulls on the oceans and causes tides."),
            _chunk(2, "Glaciers store most of the fresh water."),
            _chunk(3, "Spring tides happen when the Sun and Moon line up."),
        ]
    )
    top = index.top_k("Why do spring tides happen?", 2)
    assert top[0].id == "m:p1:3"
    assert index.top_k("glaciers fresh water", 3, exclude={"m:p1:2"}) == []


def test_previous_line_helps_find_the_subject() -> None:
    from groundcast.pipeline.verifier import passages_for

    chunks = [
        _chunk(1, "Glaciers store most of the fresh water on Earth."),
        _chunk(2, "The lake doubled in area after the dam was built."),
    ]
    index = BM25Index(chunks)
    by_id = {c.id: c for c in chunks}
    # "It grew a lot later." shares no word with any passage; the line before names the lake and the dam.
    alone = passages_for("It grew a lot later.", [], by_id, index, 1)
    with_context = passages_for("It grew a lot later.", [], by_id, index, 1,
                                context="Then the dam was built on the lake.")  # fmt: skip
    assert alone == [] and with_context[0].id == "m:p1:2"
