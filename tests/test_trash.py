import re
import sqlite3
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from groundcast import trash as trash_module
from groundcast.config import Settings
from groundcast.llm import Role, roles
from groundcast.models import Brief, Chunk, Material, SessionRecord, SessionStatus, utc_now
from groundcast.profile.concepts import add_concept, link_sources, list_concepts, merge, record_quiz, rename
from groundcast.profile.db import PROFILE_FILE, ProfileDB, list_events
from groundcast.profile.extract import extract_concepts
from groundcast.profile.feedback import Feedback, get_feedback, set_feedback
from groundcast.qa import QAExchange, QAHistory, load_history, save_history
from groundcast.quiz import Quiz, QuizAttempt, QuizFile, QuizQuestion, load_quizzes, save_quizzes
from groundcast.storage import Store
from groundcast.trash import Trash, TrashConflict
from groundcast.web.app import create_app

from .conftest import FakeBackend

Tides = tuple[Material, list[Chunk]]


@pytest.fixture
def db(settings: Settings) -> ProfileDB:
    return ProfileDB(settings.data_dir)


@pytest.fixture
def trash(store: Store, db: ProfileDB) -> Trash:
    return Trash(store, db)


def _tide_concept(db: ProfileDB, material: Material, chunks: list[Chunk], name: str = "Tide") -> str:
    with db.connect() as con:
        cid = add_concept(con, name, "", "inference")
        link_sources(con, cid, material.id, [chunks[0].id])
    return cid


def _session(store: Store, material_id: str, status: SessionStatus = SessionStatus.DONE, sid: str = "s-1") -> SessionRecord:
    record = SessionRecord(id=sid, title="Tides", brief=Brief(focus="tides", material_ids=[material_id]), status=status)
    store.save_session(record)
    return record


def _quiz(store: Store, session_id: str, quiz_id: str = "q1") -> Quiz:
    data = load_quizzes(store, session_id)
    # A second after the last quiz: two calls can share a clock tick, and a restore sorts by time.
    at = max((q.created_at for q in data.quizzes), default=utc_now()) + timedelta(seconds=1)
    quiz = Quiz(id=quiz_id, questions=[QuizQuestion(id=f"{quiz_id}-1", question="Why?", options=["a", "b"], correct=0,
                                                    explanation="", topic="Tides")], created_at=at)  # fmt: skip
    data.quizzes.append(quiz)
    data.attempts.append(QuizAttempt(id=f"{quiz_id}-a", quiz_id=quiz_id, answers=[0], score=1, created_at=at))
    save_quizzes(store, session_id, data)
    return quiz


def test_material_goes_to_the_trash_and_comes_back(store: Store, db: ProfileDB, trash: Trash, tides: Tides) -> None:
    material, chunks = tides
    _tide_concept(db, material, chunks)
    files = store.material_files(material)
    item = trash.delete_material(material.id)
    assert store.list_materials() == [] and not any(f.exists() for f in files)
    (concept,) = list_concepts(db)
    assert concept.chunks == 0  # the concept and its quiz results stay; its link to the material leaves
    removed = list_events(db, 1)[0]
    assert (removed.kind, removed.before) == ("material.removed", {"label": "tides.md", "concept_sources": 1,
                                                                  "extractions": 0})  # fmt: skip
    assert [i.id for i in trash.items()] == [item.id]

    trash.restore(item.id)
    assert [m.id for m in store.list_materials()] == [material.id] and all(f.exists() for f in files)
    assert list_concepts(db)[0].chunks == 1
    assert list_events(db, 1)[0].kind == "material.restored"
    assert trash.items() == []


def test_material_in_use_cannot_be_deleted(store: Store, trash: Trash, tides: Tides) -> None:
    material, _ = tides
    _session(store, material.id, SessionStatus.RUNNING)
    with pytest.raises(TrashConflict, match="being made"):
        trash.delete_material(material.id)
    material.status = "processing"
    store.save_material(material, store.get_chunks(material.id))
    with pytest.raises(TrashConflict, match="being read"):
        trash.delete_material(material.id)


def test_restore_refuses_when_the_material_was_added_again(settings: Settings, store: Store, trash: Trash,
                                                         tides: Tides) -> None:  # fmt: skip
    from groundcast.ingest import ingest_file

    from .conftest import FIXTURES

    material, _ = tides
    item = trash.delete_material(material.id)
    ingest_file(FIXTURES / "tides.md", store, settings)  # the same file has the same ID
    with pytest.raises(TrashConflict, match="again"):
        trash.restore(item.id)
    assert trash.get(item.id).id == item.id  # still in the trash


def test_session_takes_its_feedback_and_quiz_results(store: Store, db: ProfileDB, trash: Trash, tides: Tides) -> None:
    material, chunks = tides
    cid = _tide_concept(db, material, chunks)
    record = _session(store, material.id)
    set_feedback(db, record.id, Feedback(rating=4))
    record_quiz(db, record.id, "a1", [(cid, "q1-1", True)])
    item = trash.delete_session(record)
    assert store.list_sessions() == [] and not store.session_dir(record.id).exists()
    assert get_feedback(db, record.id) is None and list_concepts(db)[0].asked == 0
    assert item.label == "Tides"

    # A merge made while the session is in the trash: its results go to the concept the old one went into.
    other = _tide_concept(db, material, chunks, "Tides")
    merge(db, cid, other)
    trash.restore(item.id)
    assert [s.id for s in store.list_sessions()] == [record.id]
    assert get_feedback(db, record.id).rating == 4  # type: ignore[union-attr]
    (concept,) = list_concepts(db)
    assert (concept.id, concept.asked, concept.right) == (other, 1, 1)


def test_session_being_made_cannot_be_deleted(store: Store, trash: Trash, tides: Tides) -> None:
    for status in (SessionStatus.QUEUED, SessionStatus.RUNNING):
        with pytest.raises(TrashConflict):
            trash.delete_session(_session(store, tides[0].id, status))


def test_question_restores_in_its_place_once_the_session_is_back(store: Store, trash: Trash, tides: Tides) -> None:
    record = _session(store, tides[0].id)
    save_history(store, record.id, QAHistory(exchanges=[
        QAExchange(id=f"x{n}", question=f"Q{n}?", covered=True, sentences=[], asked_at=utc_now() + timedelta(seconds=n))
        for n in range(3)]))  # fmt: skip
    item = trash.delete_question(record, "x1")
    assert [x.id for x in load_history(store, record.id).exchanges] == ["x0", "x2"]
    assert (item.label, item.session_label) == ("Q1?", "Tides")
    with pytest.raises(KeyError):
        trash.delete_question(record, "x1")

    session_item = trash.delete_session(record)
    with pytest.raises(TrashConflict, match="restore the session first"):
        trash.restore(item.id)
    trash.restore(session_item.id)
    trash.restore(item.id)
    assert [x.id for x in load_history(store, record.id).exchanges] == ["x0", "x1", "x2"]


def test_quiz_takes_its_attempts_and_results(store: Store, db: ProfileDB, trash: Trash, tides: Tides) -> None:
    material, chunks = tides
    cid = _tide_concept(db, material, chunks)
    record = _session(store, material.id)
    _quiz(store, record.id, "q1")
    _quiz(store, record.id, "q2")
    record_quiz(db, record.id, "q1-a", [(cid, "q1-1", True)])
    record_quiz(db, record.id, "q2-a", [(cid, "q2-1", False)])
    item = trash.delete_quiz(record, "q1")
    data = load_quizzes(store, record.id)
    assert [q.id for q in data.quizzes] == ["q2"] and [a.quiz_id for a in data.attempts] == ["q2"]
    assert (list_concepts(db)[0].asked, list_concepts(db)[0].right) == (1, 0)
    assert item.label == "Quiz of 1 question"

    trash.restore(item.id)
    data = load_quizzes(store, record.id)
    assert [q.id for q in data.quizzes] == ["q1", "q2"] and len(data.attempts) == 2
    assert (list_concepts(db)[0].asked, list_concepts(db)[0].right) == (2, 1)


def test_restore_skips_rows_a_crash_left_in_the_profile(store: Store, db: ProfileDB, trash: Trash,
                                                       tides: Tides) -> None:  # fmt: skip
    material, chunks = tides
    cid = _tide_concept(db, material, chunks)
    record = _session(store, material.id)
    record_quiz(db, record.id, "a1", [(cid, "q1-1", True)])
    item = trash.delete_session(record)
    record_quiz(db, record.id, "a1", [(cid, "q1-1", True)])  # as if the delete had stopped before its commit
    trash.restore(item.id)
    assert list_concepts(db)[0].asked == 1


def test_a_failed_move_leaves_everything_in_place(monkeypatch: pytest.MonkeyPatch, store: Store, trash: Trash,
                                                  tides: Tides) -> None:  # fmt: skip
    material, _ = tides
    real = trash_module.move_path
    calls = []

    def flaky(src: Path, dst: Path) -> None:
        calls.append(src)
        if len(calls) == 2:
            raise PermissionError("in use")
        real(src, dst)

    monkeypatch.setattr(trash_module, "move_path", flaky)
    with pytest.raises(PermissionError):
        trash.delete_material(material.id)
    assert all(f.exists() for f in store.material_files(material))
    assert trash.items() == [] and list(trash.root.iterdir()) == []


def test_purge(store: Store, trash: Trash, tides: Tides) -> None:
    record = _session(store, tides[0].id)
    _quiz(store, record.id)
    quiz_item = trash.delete_quiz(record, "q1")
    session_item = trash.delete_session(record)
    (trash.root / "left-over").mkdir()  # a delete interrupted before it wrote item.json
    assert trash.purge_expired(0) == [] and len(trash.items()) == 2
    assert not (trash.root / "left-over").exists()
    later = utc_now() + timedelta(days=31)
    assert trash.purge_expired(30, now=utc_now()) == []
    assert sorted(trash.purge_expired(30, now=later)) == sorted([quiz_item.id, session_item.id])

    record = _session(store, tides[0].id, sid="s-2")
    _quiz(store, record.id)
    quiz_item = trash.delete_quiz(record, "q1")
    session_item = trash.delete_session(record)
    assert sorted(trash.purge(session_item.id)) == sorted([session_item.id, quiz_item.id])  # its quiz goes with it
    trash.delete_material(tides[0].id)
    assert trash.empty() == 1 and trash.items() == []


def test_trash_api(settings: Settings, store: Store, tides: Tides) -> None:
    material, _ = tides
    record = _session(store, material.id)
    _quiz(store, record.id)
    app = create_app(settings, runner=object())  # type: ignore[arg-type]
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        assert client.get("/api/settings").json()["trash_keep_days"] == settings.trash.keep_days
        quiz = client.delete(f"/api/sessions/{record.id}/quizzes/q1")
        assert quiz.status_code == 200, quiz.text
        assert client.delete(f"/api/sessions/{record.id}/quizzes/q1").json()["detail"] == "no quiz 'q1' in session s-1"
        session = client.delete(f"/api/sessions/{record.id}").json()
        assert session["kind"] == "session" and session["purge_at"] is not None
        assert client.get(f"/data/sessions/{record.id}/session.json").status_code == 404
        assert client.get("/api/sessions").json() == []
        assert client.delete("/api/sessions/nope").status_code == 404
        assert client.post(f"/api/trash/{quiz.json()['id']}/restore").status_code == 409  # the session first
        assert [e["kind"] for e in client.get("/api/trash").json()] == ["session", "quiz"]
        assert client.post(f"/api/trash/{session['id']}/restore").json()["id"] == session["id"]
        assert [s["id"] for s in client.get("/api/sessions").json()] == [record.id]

        removed = client.delete(f"/api/materials/{material.id}").json()
        assert removed["label"] == "tides.md"
        assert client.get(f"/data/materials/{material.stored_name}").status_code == 404
        assert client.delete(f"/api/trash/{removed['id']}").json() == {"deleted": [removed["id"]]}
        assert client.delete("/api/trash").json() == {"deleted": 1}
        assert client.get("/api/trash").json() == []
        assert client.post("/api/trash/x.y/restore").status_code == 404  # not a safe ID
        # Another web page in the browser cannot delete on the owner's behalf.
        r = client.delete(f"/api/sessions/{record.id}", headers={"Origin": "https://evil.example"})
        assert r.status_code == 403


def test_the_service_purges_old_items_when_it_starts(settings: Settings, store: Store, db: ProfileDB,
                                                     tides: Tides) -> None:  # fmt: skip
    trash = Trash(store, db)
    item = trash.delete_material(tides[0].id)
    old = trash.get(item.id)
    old.deleted_at -= timedelta(days=settings.trash.keep_days + 1)
    trash_module.write_model(trash.root / item.id / trash_module.ITEM_FILE, old)
    with TestClient(create_app(settings, runner=object()), base_url="http://127.0.0.1:8765"):  # type: ignore[arg-type]
        pass
    assert trash.items() == []


def test_concept_leaves_with_its_results_and_is_not_found_again(settings: Settings, db: ProfileDB, trash: Trash,
                                                               tides: Tides) -> None:  # fmt: skip
    material, chunks = tides
    cid = _tide_concept(db, material, chunks)
    record_quiz(db, "s-1", "a1", [(cid, "q1-1", True)])
    item = trash.delete_concept(cid)
    assert list_concepts(db) == [] and item.label == "Tide"
    removed = list_events(db, 1)[0]
    assert (removed.kind, removed.before) == ("concept.removed", {"label": "Tide", "quiz_results": 1})
    for change in (lambda: rename(db, cid, "Tides"), lambda: merge(db, cid, cid + "x")):
        with pytest.raises(KeyError):
            change()
    with pytest.raises(KeyError):
        trash.delete_concept(cid)
    record_quiz(db, "s-1", "a2", [(cid, "q1-1", False)])  # answers to old questions on it are not recorded

    # Extraction skips it, whether the model matches it or finds it as new under the same name.
    def found(role: Role, prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        first = re.search(r"^\[(\S+)\]", prompt, re.M).group(1)  # type: ignore[union-attr]
        return {"concepts": [{"name": "Moon pull", "description": "", "chunk_ids": [first], "match": cid},
                             {"name": "tide", "description": "", "chunk_ids": [first]},
                             {"name": "Neap tide", "description": "", "chunk_ids": [first]}]}  # fmt: skip

    extract_concepts(FakeBackend({"ConceptsOutput": found}), roles(settings.llm)["concepts"], settings, db,
                     material, chunks)  # fmt: skip
    assert [c.name for c in list_concepts(db)] == ["Neap tide"]

    trash.restore(item.id)
    (tide,) = [c for c in list_concepts(db) if c.id == cid]
    assert (tide.asked, tide.right) == (1, 1)
    assert list_events(db, 1)[0].kind == "concept.restored"


def test_purged_concept_stays_out(store: Store, db: ProfileDB, trash: Trash, tides: Tides) -> None:
    material, chunks = tides
    cid = _tide_concept(db, material, chunks)
    item = trash.delete_concept(cid)
    trash.purge(item.id)
    with db.connect() as con:
        assert con.execute("SELECT removed_at FROM concepts WHERE id = ?", (cid,)).fetchone()["removed_at"]
        assert con.execute("SELECT COUNT(*) FROM concept_sources WHERE concept_id = ?", (cid,)).fetchone()[0] == 0
    assert list_concepts(db) == []


def test_older_profiles_gain_the_removed_column(settings: Settings) -> None:
    settings.data_dir.mkdir(parents=True)
    with sqlite3.connect(settings.data_dir / PROFILE_FILE) as con:
        con.execute("CREATE TABLE concepts (id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL "
                    "DEFAULT '', created_at TEXT NOT NULL, merged_into TEXT REFERENCES concepts(id))")  # fmt: skip
    con.close()
    db = ProfileDB(settings.data_dir)
    with db.connect() as con:
        assert "removed_at" in {r["name"] for r in con.execute("PRAGMA table_info(concepts)")}


def test_concept_api(settings: Settings, db: ProfileDB, tides: Tides) -> None:
    cid = _tide_concept(db, *tides)
    with TestClient(create_app(settings, runner=object()), base_url="http://127.0.0.1:8765") as client:  # type: ignore[arg-type]
        entry = client.delete(f"/api/concepts/{cid}").json()
        assert entry["kind"] == "concept" and client.get("/api/concepts").json() == []
        assert client.delete(f"/api/concepts/{cid}").json()["detail"] == f"no concept {cid!r}"
        client.post(f"/api/trash/{entry['id']}/restore")
        assert [c["id"] for c in client.get("/api/concepts").json()] == [cid]
