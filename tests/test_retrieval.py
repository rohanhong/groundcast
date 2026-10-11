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
