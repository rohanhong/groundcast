import re
from typing import Any

import pytest
from fastapi.testclient import TestClient

from groundcast.config import Settings
from groundcast.llm import Role, roles
from groundcast.models import Brief, Chunk, Material, SessionStatus
from groundcast.profile.concepts import (
    add_concept,
    link_sources,
    list_concepts,
    merge,
    record_quiz,
    rename,
    resolve,
    slugify,
)
from groundcast.profile.db import ProfileDB, list_events
from groundcast.profile.extract import candidates, extract_concepts
from groundcast.sessions import new_session, run_session
from groundcast.storage import Store
from groundcast.web.app import create_app

from .conftest import FakeBackend, scripted_backend

Tides = tuple[Material, list[Chunk]]


@pytest.fixture
def db(settings: Settings) -> ProfileDB:
    return ProfileDB(settings.data_dir)


def _concept(db: ProfileDB, name: str, material: str = "m1", chunks: tuple[str, ...] = ("m1:p1:1",)) -> str:
    with db.connect() as con:
        cid = add_concept(con, name, f"About {name}.", "inference")
        link_sources(con, cid, material, chunks)
    return cid


def test_slugs_are_ascii_and_unique(db: ProfileDB) -> None:
    assert slugify("  Spring Tide (Sun + Moon) ") == "spring-tide-sun-moon"
    assert slugify("Caf\u00e9 effect") == "cafe-effect"
    assert _concept(db, "Tide") == "tide"
    assert _concept(db, "tide!") == "tide-2"


def test_rename_and_merge_are_logged_and_keep_history(db: ProfileDB) -> None:
    neap = _concept(db, "Neap tide", chunks=("m1:p1:1", "m1:p1:2"))
    low = _concept(db, "Low tide", material="m2", chunks=("m2:p1:1", "m1:p1:2"))
    record_quiz(db, "s1", "a1", [(neap, "q1", True), (neap, "q2", False), ("unknown", "q3", True)])

    rename(db, low, "Low water")
    merge(db, neap, low)
    (only,) = list_concepts(db)
    assert (only.id, only.name) == (low, "Low water")  # the ID stays when renamed
    assert only.material_ids == ["m1", "m2"] and only.chunks == 3
    assert (only.asked, only.right) == (2, 1)  # quiz results moved; the unknown concept was ignored
    with db.connect() as con:
        assert resolve(con, neap) == low
    kinds = [e.kind for e in list_events(db, 10)]
    assert kinds[:2] == ["concept.merged", "concept.renamed"]
    merged = list_events(db, 1)[0]
    assert (merged.source, merged.before["name"], merged.after["id"]) == ("user", "Neap tide", low)

    with pytest.raises(ValueError):
        merge(db, low, low)
    with pytest.raises(KeyError):
        merge(db, neap, low)  # already merged
    with pytest.raises(ValueError):
        rename(db, low, " ")


def test_merging_into_a_concept_redirects_earlier_merges(db: ProfileDB) -> None:
    a, b, c = (_concept(db, n) for n in ("A", "B", "C"))
    merge(db, a, b)
    merge(db, b, c)
    with db.connect() as con:
        assert resolve(con, a) == c


def test_extraction_matches_existing_concepts(settings: Settings, db: ProfileDB, tides: Tides) -> None:
    material, chunks = tides
    existing = _concept(db, "Spring tide")
    settings.concepts.batch_words = len(chunks[0].text.split())  # one passage per batch
    prompts: list[str] = []

    def found(role: Role, prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        prompts.append(prompt)
        first = re.search(r"^\[(\S+)\]", prompt, re.M).group(1)  # type: ignore[union-attr]
        # From the second batch on, the model names the concept found in the first.
        again = "tidal-range" if len(prompts) > 1 else "not-a-concept"
        return {"concepts": [
            {"name": "Spring tide", "description": "d", "chunk_ids": [first, "bogus:p1:1"], "match": existing},
            {"name": "Tidal range", "description": "d", "chunk_ids": [first], "match": again},
            {"name": "No passage", "description": "d", "chunk_ids": ["bogus:p1:1"]},
        ]}  # fmt: skip

    n = extract_concepts(FakeBackend({"ConceptsOutput": found}), roles(settings.llm)["concepts"], settings, db,
                         material, chunks)  # fmt: skip
    names = {c.name: c for c in list_concepts(db)}
    assert len(prompts) == len(chunks) > 1
    assert n == 2 and set(names) == {"Spring tide", "Tidal range"}
    assert material.id in names["Spring tide"].material_ids
    assert names["Tidal range"].chunks == len(chunks)
    assert any("- spring-tide: Spring tide." in p for p in prompts)  # shown where the words overlap
    assert list_events(db, 1)[0].kind == "concepts.extracted"


def test_candidates_share_words_with_the_text(db: ProfileDB) -> None:
    for name in ("Spring tide", "Neap tide", "Evaporation"):
        _concept(db, name)
    found = candidates(list_concepts(db), "Spring tides are larger than neap tides.", limit=5)
    assert [c.name for c in found] == ["Neap tide", "Spring tide"]
    assert candidates(list_concepts(db), "spring", limit=0) == []


def test_sessions_extract_each_material_once(settings: Settings, store: Store, db: ProfileDB, tides: Tides) -> None:
    material, _ = tides
    backend = scripted_backend()
    for _ in range(2):
        record = run_session(new_session(store, Brief(focus="tides", material_ids=[material.id], minutes=2)),
                             store, settings, backend)  # fmt: skip
        assert record.status == SessionStatus.DONE, record.error
    assert sum(t == "ConceptsOutput" for _, t, _ in backend.calls) == 1
    assert [c.name for c in list_concepts(db)] == ["Tide"]


def test_failed_extraction_does_not_stop_a_session(settings: Settings, store: Store, tides: Tides) -> None:
    material, _ = tides
    backend = scripted_backend()
    del backend.handlers["ConceptsOutput"]
    record = run_session(new_session(store, Brief(focus="tides", material_ids=[material.id], minutes=2)),
                         store, settings, backend)  # fmt: skip
    assert record.status == SessionStatus.DONE, record.error
    assert any("Skipped concepts" in line for line in record.log)


def test_concepts_api(settings: Settings, store: Store, db: ProfileDB, tides: Tides) -> None:
    material, _ = tides
    tide, sea = _concept(db, "Tide", material.id), _concept(db, "Sea", material.id)
    app = create_app(settings, runner=object(), backend=scripted_backend())  # type: ignore[arg-type]
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        assert [c["id"] for c in client.get("/api/concepts").json()] == [sea, tide]
        renamed = client.post(f"/api/concepts/{tide}/rename", json={"name": "Tides"}).json()
        assert {c["name"] for c in renamed} == {"Sea", "Tides"}
        assert [c["id"] for c in client.post(f"/api/concepts/{sea}/merge", json={"into": tide}).json()] == [tide]
        assert client.post(f"/api/concepts/{sea}/merge", json={"into": tide}).status_code == 404
        assert client.post(f"/api/concepts/{tide}/rename", json={"name": ""}).status_code == 422
        assert client.get("/api/events").json()[0]["kind"] == "concept.merged"
        assert client.delete(f"/api/materials/{material.id}").status_code == 200
        assert client.get("/api/concepts").json()[0]["chunks"] == 0
