import re
from typing import Any

from fastapi.testclient import TestClient

from groundcast.config import Settings
from groundcast.llm import Role, roles
from groundcast.models import Brief, Chunk, Material, SessionRecord, SessionStatus
from groundcast.qa import QAExchange, answer_question, load_history
from groundcast.storage import Store
from groundcast.web.app import create_app

from .conftest import FakeBackend, Handler, items_in

Tides = tuple[Material, list[Chunk]]


def tutor_backend(answer: dict[str, Any] | Handler, fail: str = "") -> FakeBackend:
    """A Tutor that returns `answer` (or calls it); the Verifier fails any sentence containing `fail`."""

    def verify(role: Role, prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        out = []
        for i in items_in(prompt):
            label = "unsupported" if fail and fail in i["text"] else "supported"
            out.append({"sentence_id": i["sentence_id"], "label": label, "rationale": "r"})
        return {"verdicts": out}

    tutor = answer if callable(answer) else (lambda role, prompt, schema: answer)
    return FakeBackend({"TutorAnswer": tutor, "VerifierOutput": verify})


def _passage_ids(prompt: str) -> list[str]:
    return re.findall(r"^\[(\S+)\]", prompt, re.M)


def test_answer_cites_retrieved_passages_and_flags_failures(settings: Settings, tides: Tides) -> None:
    material, chunks = tides

    def tutor(role: Role, prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        first = _passage_ids(prompt)[0]
        return {
            "covered": True,
            "sentences": [
                {"text": "The Moon causes tides.", "sources": [first, "bogus:p1:1"]},
                {"text": "It also moves the continents.", "sources": [first]},
            ],
        }

    backend = tutor_backend(tutor, fail="continents")
    x = answer_question(backend, roles(settings.llm), settings, chunks, {material.id: material}, "Why tides?", [])

    tutor_prompt = next(p for role, _, p in backend.calls if role == "tutor")
    assert len(_passage_ids(tutor_prompt)) <= settings.qa.top_k
    assert x.covered
    assert [s.verified for s in x.sentences] == [True, False]
    assert x.sentences[1].label == "unsupported"
    assert x.sentences[0].sources == [_passage_ids(tutor_prompt)[0]]  # the unknown ID is removed
    assert [s.chunk_id for s in x.sources] == x.sentences[0].sources
    assert x.sources[0].path == f"materials/{material.id}.view.html#p1-{x.sources[0].chunk_id.rsplit(':', 1)[1]}"
    # The first answer sentence is checked with the question as its context.
    check = next(p for role, _, p in backend.calls if role == "verifier")
    assert "previous sentence: Learner: Why tides?" in check


def test_follow_up_sees_earlier_exchange_and_verification_can_be_off(settings: Settings, tides: Tides) -> None:
    material, chunks = tides
    settings.qa.verify = False
    earlier = QAExchange(
        id="e1", question="What causes spring tides?", covered=True, sentences=[{"text": "Sun and Moon align."}]
    )
    backend = tutor_backend({"covered": False, "sentences": [{"text": "Your materials do not say."}]})
    x = answer_question(
        backend, roles(settings.llm), settings, chunks, {material.id: material}, "And neap ones?", [earlier]
    )
    prompt = backend.calls[0][2]
    assert "Learner: What causes spring tides?\nTutor: Sun and Moon align." in prompt
    assert [role for role, _, _ in backend.calls] == ["tutor"]  # no Verifier call
    assert not x.covered and x.sources == []


def _done_session(store: Store, material_id: str, status: SessionStatus = SessionStatus.DONE) -> str:
    record = SessionRecord(id="s-1", brief=Brief(focus="tides", material_ids=[material_id]), status=status)
    store.save_session(record)
    return record.id


def test_questions_api_saves_history(settings: Settings, store: Store, tides: Tides) -> None:
    material, _ = tides
    session_id = _done_session(store, material.id)
    backend = tutor_backend({"covered": True, "sentences": [{"text": "The Moon causes tides."}]})
    app = create_app(settings, runner=object(), backend=backend)  # type: ignore[arg-type]
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        assert client.get(f"/api/sessions/{session_id}/questions").json() == []
        r = client.post(f"/api/sessions/{session_id}/questions", json={"question": "  Why tides?  "})
        assert r.status_code == 200, r.text
        assert r.json()["question"] == "Why tides?"
        assert [x["question"] for x in client.get(f"/api/sessions/{session_id}/questions").json()] == ["Why tides?"]
        assert client.post(f"/api/sessions/{session_id}/questions", json={"question": " "}).status_code == 422
        assert client.post("/api/sessions/nope/questions", json={"question": "x"}).status_code == 404
        # Another web page in the browser cannot ask on the owner's behalf.
        r = client.post(
            f"/api/sessions/{session_id}/questions", json={"question": "x"}, headers={"Origin": "https://evil.example"}
        )
        assert r.status_code == 403
    assert len(load_history(store, session_id).exchanges) == 1


def test_questions_wait_for_a_finished_session(settings: Settings, store: Store, tides: Tides) -> None:
    material, _ = tides
    session_id = _done_session(store, material.id, SessionStatus.FAILED)
    app = create_app(settings, runner=object(), backend=tutor_backend({}))  # type: ignore[arg-type]
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        r = client.post(f"/api/sessions/{session_id}/questions", json={"question": "Why tides?"})
    assert r.status_code == 409
